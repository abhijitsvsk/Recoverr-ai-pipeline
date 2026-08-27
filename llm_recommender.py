"""
LLM Recommendation Engine for RecoverAI Payment Recovery Agent.
Evaluates structured payment context using real LLM calls via Ollama local endpoint (gemma3:1b).
"""

import json
import os
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List

from db import get_connection
from models import PaymentStatus

ALLOWED_ACTIONS = {"RETRY", "SEND_RECOVERY_LINK", "ESCALATE", "STOP"}

DEFAULT_HIGH_VALUE_THRESHOLD_INR = 10000


def get_high_value_threshold_inr() -> int:
    """Read HIGH_VALUE_THRESHOLD_INR from environment or default to 10000."""
    val = os.environ.get("HIGH_VALUE_THRESHOLD_INR")
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    return DEFAULT_HIGH_VALUE_THRESHOLD_INR


PROMPT_TEMPLATE = """You are an AI Payment Recovery Advisor evaluating failed payment interventions.
Your job is strictly to RECOMMEND an intervention with clear, context-sensitive reasoning.
You have NO authority to execute actions or move money directly. Your recommendation will be independently reviewed by a deterministic Policy Engine.

POLICY DIRECTIVES FOR RECOMMENDING ACTIONS:
- If Category is "TEMPORARY":
  * If Retry Budget Remaining > 0 -> recommend "RETRY" (automatic retry).
  * If Retry Budget Remaining == 0 -> recommend "SEND_RECOVERY_LINK".
- If Category is "PERMANENT":
  * Always recommend "SEND_RECOVERY_LINK" (retries will always fail for hard declined / cancelled / expired payment methods).
- If Category is "REPEATED_FAILURE":
  * Always recommend "ESCALATE" (3+ failed attempts require human ops review, never auto-retry).
- If Category is "UNKNOWN":
  * If High Value is True (> INR 10,000) -> recommend "STOP" (halt recovery due to high risk).
  * If High Value is False (<= INR 10,000) -> recommend "ESCALATE" (escalate unmapped code for manual investigation).

ALLOWED ACTIONS (Choose exactly ONE):
- RETRY
- SEND_RECOVERY_LINK
- ESCALATE
- STOP

PAYMENT CONTEXT:
- Payment ID: {payment_id}
- Category: {category}
- Attempt Count: {attempt_count}
- Amount: INR {amount_in_inr:,.2f} ({amount_in_paise} paise)
- Time Since Last Attempt: {time_since_last_attempt}
- Retry Budget Remaining: {retry_budget_remaining}
- High Value (> INR {high_value_threshold_inr:,}): {exceeds_high_value_threshold}

Respond ONLY in valid JSON format:
{{
  "recommended_action": "<RETRY|SEND_RECOVERY_LINK|ESCALATE|STOP>",
  "reason": "<1-2 sentence justification referencing the specific category, attempt count, amount, and policy context above>"
}}
"""


def compute_time_since_last_attempt(last_attempt_at_str: str) -> str:
    """Format human readable time since last attempt."""
    if not last_attempt_at_str:
        return "Unknown"

    try:
        dt = datetime.fromisoformat(last_attempt_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt

        total_hours = int(diff.total_seconds() // 3600)
        if total_hours < 1:
            mins = int(diff.total_seconds() // 60)
            return f"{mins} minutes ago"
        elif total_hours < 24:
            return f"{total_hours} hours ago"
        else:
            days = total_hours // 24
            return f"{days} days ago ({total_hours} hours)"
    except Exception:
        return "Recently"


def call_llm_api(context: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """
    Call Ollama API using mistral:latest (7B local model).
    """
    prompt = PROMPT_TEMPLATE.format(**context)
    url = "http://127.0.0.1:11434/api/generate"

    payload = {
        "model": "mistral:latest",
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "num_predict": 96,
            "temperature": 0.0,
            "seed": 42
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw_response = resp.read().decode("utf-8")
            data = json.loads(raw_response)
            response_text = data.get("response", "").strip()
            if response_text.startswith("```"):
                lines = response_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                response_text = "\n".join(lines).strip()

            parsed = json.loads(response_text)
            action = str(parsed.get("recommended_action", "")).strip().upper()
            reason = str(parsed.get("reason", "")).strip()

            if action in ALLOWED_ACTIONS and reason:
                return action, reason, None
            else:
                return None, None, f"Invalid LLM output: action='{action}', reason='{reason}'"

    except Exception as e:
        return None, None, f"LLM API Error: {type(e).__name__}: {str(e)}"


def generate_context_aware_fallback(context: Dict[str, Any]) -> Tuple[str, str]:
    """Fallback handler returning safe default recommendation (ESCALATE) per specification."""
    cat = context["category"]
    amt_inr = context["amount_in_inr"]
    return "ESCALATE", f"LLM call fallback triggered for {cat} payment of INR {amt_inr:,.2f}. Defaulting to ESCALATE."


def recommend_for_payment(context: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """
    Generate recommendation for payment using real LLM API with fallback tracking.
    Returns (recommended_action, reason, error_if_fallback).
    """
    action, reason, error_msg = call_llm_api(context)

    if error_msg:
        fallback_action, fallback_reason = generate_context_aware_fallback(context)
        return fallback_action, fallback_reason, error_msg

    return action, reason, None


def process_recommendation_pipeline(db_path: str = "recover_ai.db") -> Dict[str, Any]:
    """
    Fetch all payments with status = 'CLASSIFIED'.
    Build structured context, call real LLM across all payments, update payments table,
    and write RECOMMENDED audit_log entries.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, amount_in_paise, failure_reason, category, attempt_count, last_attempt_at 
        FROM payments 
        WHERE status = ? AND category IS NOT NULL;
        """,
        (PaymentStatus.CLASSIFIED.value,),
    )
    classified_payments = cursor.fetchall()

    high_value_thresh_inr = get_high_value_threshold_inr()
    high_value_thresh_paise = high_value_thresh_inr * 100

    recommended_count = 0
    fallback_records = []
    now_str = datetime.now(timezone.utc).isoformat()

    def process_single_payment(item):
        i, row = item
        payment_id = row["id"]
        amount_in_paise = row["amount_in_paise"]
        amount_in_inr = amount_in_paise / 100.0
        category = row["category"]
        attempt_count = row["attempt_count"]
        last_attempt_at = row["last_attempt_at"]

        retries_used = max(0, attempt_count - 1)
        retry_budget_remaining = max(0, 2 - retries_used)

        time_since = compute_time_since_last_attempt(last_attempt_at)
        is_high_value = amount_in_paise > high_value_thresh_paise

        context = {
            "payment_id": payment_id,
            "category": category,
            "attempt_count": attempt_count,
            "amount_in_paise": amount_in_paise,
            "amount_in_inr": amount_in_inr,
            "last_attempt_at": last_attempt_at,
            "time_since_last_attempt": time_since,
            "retry_budget_remaining": retry_budget_remaining,
            "exceeds_high_value_threshold": is_high_value,
            "high_value_threshold_inr": high_value_thresh_inr,
        }

        action, reason, error_msg = recommend_for_payment(context)

        return {
            "i": i,
            "payment_id": payment_id,
            "amount_in_paise": amount_in_paise,
            "category": category,
            "attempt_count": attempt_count,
            "action": action,
            "reason": reason,
            "error_msg": error_msg,
        }

    from concurrent.futures import ThreadPoolExecutor, as_completed

    items = list(enumerate(classified_payments, 1))
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_item = {executor.submit(process_single_payment, item): item for item in items}
        
        for future in as_completed(future_to_item):
            res = future.result()
            payment_id = res["payment_id"]
            action = res["action"]
            reason = res["reason"]
            error_msg = res["error_msg"]
            attempt_count = res["attempt_count"]
            category = res["category"]
            amount_in_paise = res["amount_in_paise"]
            i = res["i"]

            if error_msg:
                fallback_records.append({"payment_id": payment_id, "error": error_msg})

            cursor.execute(
                """
                UPDATE payments
                SET recommended_action = ?, recommendation_reason = ?, status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (action, reason, PaymentStatus.RECOMMENDED.value, now_str, payment_id),
            )

            audit_id = f"aud_rec_{payment_id}_{random.randint(1000, 9999)}"
            event_id = f"evt_rec_{payment_id}_{random.randint(1000, 9999)}"

            cursor.execute(
                """
                INSERT INTO audit_log (
                    id, event_id, event_type, payment_id, attempt_number, timestamp,
                    category, recommended_action, policy_decision, policy_reason,
                    action_taken, execution_result, business_outcome, amount_in_paise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    audit_id,
                    event_id,
                    "RECOMMENDED",
                    payment_id,
                    attempt_count,
                    now_str,
                    category,
                    action,
                    None,
                    None,
                    None,
                    None,
                    None,
                    amount_in_paise,
                ),
            )
            conn.commit()
            recommended_count += 1
            if recommended_count % 5 == 0 or recommended_count == len(classified_payments):
                print(f"  [{recommended_count}/{len(classified_payments)}] Processed {payment_id} -> {action}", flush=True)

    conn.close()

    return {
        "processed_count": len(classified_payments),
        "recommended_count": recommended_count,
        "fallback_count": len(fallback_records),
        "fallback_records": fallback_records,
    }
