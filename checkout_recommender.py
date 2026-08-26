"""
LLM Recommendation Module for Checkout Abandonment Loop 2.
Constructs structured context for classified checkouts, calls local mistral:latest model,
validates output, updates checkouts table, and writes audit log entries.
100% separate from Loop 1 payment recommendation module.
"""

import json
import logging
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from checkout_db import get_checkout_connection
from checkout_models import CheckoutCategory, CheckoutStatus, CheckoutRecoveryAction

# Threshold constants matching Loop 2 classification
CHECKOUT_HIGH_VALUE_THRESHOLD_INR = 10000
CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE = CHECKOUT_HIGH_VALUE_THRESHOLD_INR * 100

OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "mistral:latest"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("checkout_recommender")

ALLOWED_ACTIONS = {action.value for action in CheckoutRecoveryAction}

PROMPT_TEMPLATE = """You are the AI Recommendation Engine for Checkout Abandonment Recovery in an e-commerce platform.
YOUR ROLE IS TO RECOMMEND ONLY. You DO NOT have execution authority. Your recommendation will be passed to a separate deterministic Policy Engine that will enforce merchant risk rules before any action is executed.

Structured Context for this Abandoned Checkout:
- Category: {category}
- Cart Value (in paise): {cart_value_in_paise} (INR {cart_value_in_inr:.2f})
- Abandon Count: {abandon_count}
- Customer Abandon Reason: "{customer_abandon_reason}"
- Time Since Abandoned: {time_since_abandoned}
- Reminder or Nudge Already Sent: {reminder_or_nudge_already_sent}
- Exceeds High Value Threshold (> INR 10,000): {exceeds_high_value_threshold}

Guidance for Decision Making (Evaluate the specific context nuances):
1. RECENT_ABANDON (Abandoned recently, abandon_count = 1):
   - If cart value is low (< INR 3,000 / 300,000 paise) or reason is a standard exit ('inactivity_timeout_15m', 'tab_closed_active_cart'): Recommend SEND_CART_REMINDER (a simple, low-cost reminder without margin loss).
   - If cart value is moderate (INR 3,000 - INR 10,000) or explicit exit intent ('exit_intent_popup'): Recommend SEND_DISCOUNT_NUDGE (an incentive to close the sale).
   - If cart value is near high-value threshold (> INR 8,000): Recommend ESCALATE.

2. STALE_ABANDON (Abandoned > 60 mins ago, abandon_count = 1):
   - If abandoned 1-24 hours ago with moderate cart value: Recommend SEND_DISCOUNT_NUDGE to re-engage stale shopper.
   - If abandoned > 24 hours ago ('inactivity_timeout_24h', 'abandoned_cart_reminder_unopened') or low cart value (< INR 1,500): Recommend STOP (do not waste discounts on stale or low-value carts).

3. REPEAT_ABANDONER (Customer abandoned multiple times, abandon_count >= 2):
   - If abandon_count >= 3 or cart value > INR 3,000: Recommend ESCALATE (repeated drop-offs require human ops reachout).
   - If abandon_count == 2 and cart value is low (< INR 3,000): Recommend SEND_DISCOUNT_NUDGE.

4. HIGH_VALUE_ABANDON (Cart value > INR 10,000 / 1,000,000 paise):
   - Large revenue at risk (> INR 10,000): Recommend ESCALATE for VIP sales/ops concierge handling.
   - If very recent (< 30 minutes) without discounting: Recommend SEND_CART_REMINDER.
   - If high risk or repeat high value: Recommend STOP.

5. UNKNOWN_ABANDON (Unrecognized or unmapped abandon reason):
   - SAFETY RULE: Unidentified abandon cause requires manual human review — MUST recommend ESCALATE. NEVER recommend automated actions (SEND_CART_REMINDER or SEND_DISCOUNT_NUDGE).

Required Output Format:
Return ONLY a raw JSON object (no markdown, no conversation, no explanation outside JSON) with exactly these keys:
{{
  "recommended_action": "<EXACTLY ONE OF: SEND_CART_REMINDER, SEND_DISCOUNT_NUDGE, ESCALATE, STOP>",
  "reason": "<A concise 1-2 sentence justification referencing specific values from the structured context above (e.g. cart value, abandon count, elapsed time)>"
}}
"""



def compute_time_since_abandoned(abandoned_at_str: str) -> str:
    """Compute human-readable time elapsed since abandonment."""
    try:
        abandoned_at = datetime.fromisoformat(abandoned_at_str)
        now = datetime.now(timezone.utc)
        delta = now - abandoned_at
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} minutes ago"
        hours = round(minutes / 60.0, 1)
        if hours < 24:
            return f"{hours} hours ago"
        days = round(hours / 24.0, 1)
        return f"{days} days ago"
    except Exception:
        return abandoned_at_str


def build_prompt(checkout_row: Dict[str, Any]) -> str:
    """Construct structured context and populate LLM prompt template."""
    cart_val_paise = checkout_row["cart_value_in_paise"]
    cart_val_inr = cart_val_paise / 100.0
    time_since = compute_time_since_abandoned(checkout_row["abandoned_at"])
    exceeds_threshold = cart_val_paise > CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE

    return PROMPT_TEMPLATE.format(
        category=checkout_row["category"],
        cart_value_in_paise=cart_val_paise,
        cart_value_in_inr=cart_val_inr,
        abandon_count=checkout_row["abandon_count"],
        customer_abandon_reason=checkout_row["customer_abandon_reason"],
        time_since_abandoned=time_since,
        reminder_or_nudge_already_sent=False,
        exceeds_high_value_threshold=exceeds_threshold,
    )


def parse_llm_json_response(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Clean markdown fences and parse JSON payload for action and reason."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        action = data.get("recommended_action")
        reason = data.get("reason")
        return action, reason
    except Exception as e:
        # Attempt to auto-repair simple truncation (e.g. unclosed JSON string or brace)
        try:
            repaired = cleaned
            if not repaired.endswith("}"):
                if not repaired.endswith('"'):
                    repaired += '"'
                repaired += "}"
            data = json.loads(repaired)
            action = data.get("recommended_action")
            reason = data.get("reason")
            if action and reason:
                logger.info(f"Successfully auto-repaired truncated JSON response for action: {action}")
                return action, reason
        except Exception:
            pass

        logger.warning(f"Failed to parse LLM JSON: {e}. Raw text: {raw_text}")
        return None, None



def call_llm(prompt: str) -> Tuple[str, str, bool]:
    """
    Call local Ollama mistral:latest endpoint.
    Returns (recommended_action, reason, is_fallback).
    """
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "seed": 42,
            "num_predict": 128,
        },



    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")

            response_json = json.loads(body)
            raw_response = response_json.get("response", "")

            action, reason = parse_llm_json_response(raw_response)

            if action in ALLOWED_ACTIONS and reason:
                return action, reason, False
            else:
                logger.warning(f"Invalid LLM output: action='{action}', reason='{reason}'")
                return (
                    CheckoutRecoveryAction.ESCALATE.value,
                    "Fallback: Malformed LLM output or unallowed action. Defaulted to ESCALATE for safety.",
                    True,
                )

    except Exception as exc:
        logger.error(f"Ollama API call error: {exc}")
        return (
            CheckoutRecoveryAction.ESCALATE.value,
            f"Fallback: LLM connection or execution error ({type(exc).__name__}). Defaulted to ESCALATE for safety.",
            True,
        )


def process_single_recommendation(checkout_row: Dict[str, Any]) -> Dict[str, Any]:
    """Process LLM recommendation for a single checkout row."""
    checkout_id = checkout_row["id"]
    prompt = build_prompt(checkout_row)
    action, reason, is_fallback = call_llm(prompt)

    return {
        "checkout_id": checkout_id,
        "category": checkout_row["category"],
        "cart_value_in_paise": checkout_row["cart_value_in_paise"],
        "abandon_count": checkout_row["abandon_count"],
        "customer_abandon_reason": checkout_row["customer_abandon_reason"],
        "abandoned_at": checkout_row["abandoned_at"],
        "recommended_action": action,
        "recommendation_reason": reason,
        "is_fallback": is_fallback,
        "prompt_used": prompt,
    }


def process_checkout_recommendation_pipeline(
    db_path: str = "checkout_recovery.db", max_workers: int = 4
) -> Dict[str, Any]:




    """
    Batch-process all checkouts with status = 'CLASSIFIED'.
    Call LLM recommender, update database, and insert audit log entries.
    """
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, cart_value_in_paise, customer_abandon_reason, category, abandon_count, abandoned_at
        FROM checkouts
        WHERE status = ?;
        """,
        (CheckoutStatus.CLASSIFIED.value,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        logger.info("No checkouts with status = CLASSIFIED found for recommendation pipeline.")
        return {"processed_count": 0, "fallback_count": 0, "results": []}

    results = []
    fallback_count = 0
    fallback_ids = []

    logger.info(f"Starting LLM recommendation pipeline for {len(rows)} checkouts using model '{MODEL_NAME}' (max_workers={max_workers})...")

    completed_count = 0
    total_count = len(rows)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_row = {executor.submit(process_single_recommendation, row): row for row in rows}
        for future in as_completed(future_to_row):
            res = future.result()
            results.append(res)
            completed_count += 1
            if res["is_fallback"]:
                fallback_count += 1
                fallback_ids.append(res["checkout_id"])

            logger.info(
                f"[{completed_count:3d}/{total_count:3d}] Processed {res['checkout_id']} ({res['category']}) -> "
                f"Action: {res['recommended_action']}"
            )

            # Live DB commit per completed checkout
            conn_item = get_checkout_connection(db_path)
            cursor_item = conn_item.cursor()
            now_str = datetime.now(timezone.utc).isoformat()
            checkout_id = res["checkout_id"]
            action = res["recommended_action"]
            reason = res["recommendation_reason"]
            category = res["category"]
            cart_val_paise = res["cart_value_in_paise"]

            with conn_item:
                cursor_item.execute(
                    """
                    UPDATE checkouts
                    SET recommended_action = ?, recommendation_reason = ?, status = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (action, reason, CheckoutStatus.RECOMMENDED.value, now_str, checkout_id),
                )

                audit_id = f"aud_rec_{checkout_id}"
                event_id = f"evt_rec_{checkout_id}"

                cursor_item.execute(
                    """
                    INSERT INTO checkout_audit_log (
                        id, event_id, event_type, checkout_id, timestamp,
                        category, recommended_action, policy_decision, policy_reason,
                        action_taken, execution_result, business_outcome, cart_value_in_paise
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        audit_id,
                        event_id,
                        "RECOMMENDED",
                        checkout_id,
                        now_str,
                        category,
                        action,
                        None,
                        None,
                        None,
                        None,
                        None,
                        cart_val_paise,
                    ),
                )
            conn_item.close()


    return {
        "processed_count": len(rows),
        "recommended_count": len(results),
        "fallback_count": fallback_count,
        "fallback_ids": fallback_ids,
        "results": results,
    }
