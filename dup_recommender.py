"""
LLM Recommendation Engine for Loop 3: Duplicate Charge Detection.
Generates candidate action advice (AUTO_REFUND / HOLD_FOR_REVIEW / ESCALATE_AS_FRAUD / NO_ACTION).
Governed strictly by downstream Policy Engine.
"""

import os
import json
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List

from dup_models import DupCategory, DupAction, DupStatus
from dup_db import get_dup_connection

DUP_PROMPT_TEMPLATE = """You are an AI Duplicate Charge Recovery Advisor for an e-commerce platform.
Analyze the candidate duplicate charge context below and recommend ONE recovery action.

CONTEXT:
- Charge ID: {charge_id}
- Customer ID: {customer_id}
- Order ID: {order_id}
- Category: {category}
- Amount: INR {amount_in_inr:.2f} ({amount_in_paise} paise)
- Time Delta Since Initial Charge: {time_delta_seconds} seconds
- Prior Duplicate Flags Count: {prior_duplicate_count}
- Purchase Pattern: {purchase_type}

RULES FOR YOUR RECOMMENDATION:
1. EXACT_DUPLICATE: Recommend AUTO_REFUND unless high-value or repeat offender.
2. LIKELY_DUPLICATE: Recommend AUTO_REFUND unless suspicious.
3. SUSPECTED_DUPLICATE: Recommend HOLD_FOR_REVIEW (different payment instrument used).
4. UNRELATED: Recommend NO_ACTION (legitimate distinct purchases).
5. If prior_duplicate_count >= 2: Recommend ESCALATE_AS_FRAUD.

Allowed actions: AUTO_REFUND, HOLD_FOR_REVIEW, ESCALATE_AS_FRAUD, NO_ACTION.

Respond ONLY with valid JSON in this exact structure:
{{
    "recommended_action": "AUTO_REFUND | HOLD_FOR_REVIEW | ESCALATE_AS_FRAUD | NO_ACTION",
    "reason": "Short explanation of your recommendation"
}}
"""


def call_dup_llm(context: Dict[str, Any]) -> Tuple[str, str]:
    cat = context["category"]
    prior = context.get("prior_duplicate_count", 0)

    # Heuristic default fallback
    if prior >= 2:
        default_act = DupAction.ESCALATE_AS_FRAUD.value
        default_reason = "Customer has 2+ prior duplicate flags; suspect repeat fraud pattern."
    elif cat == DupCategory.EXACT_DUPLICATE.value:
        default_act = DupAction.AUTO_REFUND.value
        default_reason = "Identical order and payment instrument within 60m window; clear double charge."
    elif cat == DupCategory.LIKELY_DUPLICATE.value:
        default_act = DupAction.AUTO_REFUND.value
        default_reason = "Same customer, amount, and card within 30s; rapid re-checkout duplicate."
    elif cat == DupCategory.SUSPECTED_DUPLICATE.value:
        default_act = DupAction.HOLD_FOR_REVIEW.value
        default_reason = "Different payment instrument used; requires manual ops review."
    else:
        default_act = DupAction.NO_ACTION.value
        default_reason = "Legitimate distinct purchase pattern (unrelated charges)."

    try:
        url = "http://127.0.0.1:11434/api/generate"
        prompt_text = DUP_PROMPT_TEMPLATE.format(**context)
        payload = {
            "model": "mistral:latest",
            "prompt": prompt_text,
            "stream": False,
            "format": "json",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(res_json.get("response", "{}"))
            act = parsed.get("recommended_action", default_act)
            reason = parsed.get("reason", default_reason)
            if act in [a.value for a in DupAction]:
                return act, reason
    except Exception:
        pass

    return default_act, default_reason


def process_dup_recommendation_pipeline(db_path: str = "duplicate_charge.db") -> List[Dict[str, Any]]:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, customer_id, order_id, card_id, amount_in_paise,
               category, time_delta_seconds, prior_duplicate_count, purchase_type
        FROM duplicate_charges
        WHERE status = 'CLASSIFIED';
    """)
    rows = cursor.fetchall()

    recommendations = []
    now_str = datetime.now(timezone.utc).isoformat()

    for r in rows:
        cid = r["id"]
        ctx = {
            "charge_id": cid,
            "customer_id": r["customer_id"],
            "order_id": r["order_id"],
            "card_id": r["card_id"],
            "amount_in_paise": r["amount_in_paise"],
            "amount_in_inr": r["amount_in_paise"] / 100.0,
            "category": r["category"],
            "time_delta_seconds": r["time_delta_seconds"],
            "prior_duplicate_count": r["prior_duplicate_count"],
            "purchase_type": r["purchase_type"],
        }

        rec_act, rec_reason = call_dup_llm(ctx)

        cursor.execute(
            """
            UPDATE duplicate_charges
            SET recommended_action = ?, recommendation_reason = ?, status = 'RECOMMENDED', updated_at = ?
            WHERE id = ?;
            """,
            (rec_act, rec_reason, now_str, cid),
        )

        event_id = f"evt_dup_rec_{cid}"
        cursor.execute(
            """
            INSERT INTO dup_audit_log (
                id, event_id, event_type, charge_id, timestamp,
                amount_in_paise, category, recommended_action, policy_decision,
                policy_reason, action_taken, execution_result, business_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                f"aud_rec_{cid}", event_id, "RECOMMENDED", cid, now_str,
                r["amount_in_paise"], r["category"], rec_act, None,
                rec_reason, "RECOMMEND", "recommended", rec_act,
            ),
        )

        cursor.execute(
            """
            INSERT INTO dup_idempotency (event_id, charge_id, processed_at)
            VALUES (?, ?, ?);
            """,
            (event_id, cid, now_str),
        )

        recommendations.append({
            "charge_id": cid,
            "category": r["category"],
            "recommended_action": rec_act,
            "reason": rec_reason,
        })

    conn.commit()
    conn.close()
    return recommendations
