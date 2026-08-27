"""
Deterministic Policy Engine for Loop 3: Duplicate Charge Detection.
Absolute Veto Power and Hard Overrides over LLM Recommendations.
Zero AI — pure deterministic Python code.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List

from dup_models import DupCategory, DupAction, DupStatus
from dup_db import get_dup_connection

DUP_HIGH_VALUE_THRESHOLD_INR = 40000
DUP_HIGH_VALUE_THRESHOLD_PAISE = DUP_HIGH_VALUE_THRESHOLD_INR * 100  # ₹40,000 (4,000,000 paise)


def evaluate_dup_policy(context: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Evaluate candidate charge recommendation against deterministic policy rules.
    Returns (policy_decision, policy_reason, approved_action).
    """
    category = context["category"]
    amount_paise = context["amount_in_paise"]
    rec_action = context["recommended_action"]
    prior_dups = context.get("prior_duplicate_count", 0)

    amount_inr = amount_paise / 100.0

    # Rule 1: REPEAT PATTERN HARD OVERRIDE
    # Customer with 2+ prior duplicate flags is forced to ESCALATE_AS_FRAUD
    if prior_dups >= 2:
        if rec_action != DupAction.ESCALATE_AS_FRAUD.value:
            return (
                "BLOCKED",
                f"BLOCKED: Repeat pattern override — customer has {prior_dups} prior duplicate flags. Recommended action '{rec_action}' blocked; mandatory action is ESCALATE_AS_FRAUD.",
                DupAction.ESCALATE_AS_FRAUD.value,
            )
        else:
            return (
                "APPROVED",
                f"APPROVED: Repeat pattern override matched — mandatory ESCALATE_AS_FRAUD approved for customer with {prior_dups} prior flags.",
                DupAction.ESCALATE_AS_FRAUD.value,
            )

    # Rule 2: UNRELATED (FALSE POSITIVE HANDLING)
    if category == DupCategory.UNRELATED.value:
        if rec_action == DupAction.NO_ACTION.value:
            return (
                "APPROVED",
                "APPROVED: UNRELATED category (legitimate purchase pattern); NO_ACTION approved.",
                DupAction.NO_ACTION.value,
            )
        else:
            return (
                "BLOCKED",
                f"BLOCKED: Category UNRELATED permits action NO_ACTION only. Recommended '{rec_action}' blocked.",
                DupAction.NO_ACTION.value,
            )

    # Rule 3: SUSPECTED_DUPLICATE (Different payment instrument)
    if category == DupCategory.SUSPECTED_DUPLICATE.value:
        if rec_action == DupAction.HOLD_FOR_REVIEW.value:
            return (
                "APPROVED",
                "APPROVED: SUSPECTED_DUPLICATE (multi-instrument retry) permits HOLD_FOR_REVIEW.",
                DupAction.HOLD_FOR_REVIEW.value,
            )
        else:
            return (
                "BLOCKED",
                f"BLOCKED: Category SUSPECTED_DUPLICATE permits HOLD_FOR_REVIEW only. Recommended '{rec_action}' blocked (never auto-refund on different payment instrument).",
                DupAction.HOLD_FOR_REVIEW.value,
            )

    # Rule 4: EXACT_DUPLICATE & LIKELY_DUPLICATE Amount Threshold
    if category in (DupCategory.EXACT_DUPLICATE.value, DupCategory.LIKELY_DUPLICATE.value):
        if amount_paise > DUP_HIGH_VALUE_THRESHOLD_PAISE:
            # High-value duplicate (>₹40,000) forces HOLD_FOR_REVIEW
            if rec_action != DupAction.HOLD_FOR_REVIEW.value:
                return (
                    "BLOCKED",
                    f"BLOCKED: High-value threshold override — amount INR {amount_inr:,.2f} exceeds threshold (INR 40,000) in '{category}'. Action '{rec_action}' blocked; mandatory action is HOLD_FOR_REVIEW.",
                    DupAction.HOLD_FOR_REVIEW.value,
                )
            else:
                return (
                    "APPROVED",
                    f"APPROVED: High-value HOLD_FOR_REVIEW matched for amount INR {amount_inr:,.2f}.",
                    DupAction.HOLD_FOR_REVIEW.value,
                )
        else:
            # Standard amount (<=₹40,000) permits AUTO_REFUND
            if rec_action == DupAction.AUTO_REFUND.value:
                return (
                    "APPROVED",
                    f"APPROVED: AUTO_REFUND allowed for category '{category}' with amount INR {amount_inr:,.2f} <= INR 40,000.",
                    DupAction.AUTO_REFUND.value,
                )
            elif rec_action == DupAction.HOLD_FOR_REVIEW.value:
                return (
                    "APPROVED",
                    f"APPROVED: HOLD_FOR_REVIEW allowed for category '{category}'.",
                    DupAction.HOLD_FOR_REVIEW.value,
                )
            else:
                return (
                    "BLOCKED",
                    f"BLOCKED: Action '{rec_action}' is not allowed for category '{category}'.",
                    DupAction.HOLD_FOR_REVIEW.value,
                )

    return ("BLOCKED", f"BLOCKED: Category '{category}' unrecognized.", DupAction.HOLD_FOR_REVIEW.value)


def process_dup_policy_pipeline(db_path: str = "duplicate_charge.db") -> List[Dict[str, Any]]:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, category, amount_in_paise, recommended_action, prior_duplicate_count
        FROM duplicate_charges
        WHERE status = 'RECOMMENDED';
    """)
    rows = cursor.fetchall()

    policy_results = []
    now_str = datetime.now(timezone.utc).isoformat()

    for r in rows:
        cid = r["id"]
        ctx = {
            "charge_id": cid,
            "category": r["category"],
            "amount_in_paise": r["amount_in_paise"],
            "recommended_action": r["recommended_action"],
            "prior_duplicate_count": r["prior_duplicate_count"],
        }

        pol_dec, pol_reason, final_act = evaluate_dup_policy(ctx)

        new_status = DupStatus.APPROVED.value if pol_dec == "APPROVED" else DupStatus.BLOCKED.value

        cursor.execute(
            """
            UPDATE duplicate_charges
            SET policy_decision = ?, policy_reason = ?, status = ?, updated_at = ?
            WHERE id = ?;
            """,
            (pol_dec, pol_reason, new_status, now_str, cid),
        )

        event_id = f"evt_dup_pol_{cid}"
        cursor.execute(
            """
            INSERT INTO dup_audit_log (
                id, event_id, event_type, charge_id, timestamp,
                amount_in_paise, category, recommended_action, policy_decision,
                policy_reason, action_taken, execution_result, business_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                f"aud_pol_{cid}", event_id, "POLICY_DECISION", cid, now_str,
                r["amount_in_paise"], r["category"], r["recommended_action"], pol_dec,
                pol_reason, final_act, pol_dec.lower(), new_status.lower(),
            ),
        )

        cursor.execute(
            """
            INSERT INTO dup_idempotency (event_id, charge_id, processed_at)
            VALUES (?, ?, ?);
            """,
            (event_id, cid, now_str),
        )

        policy_results.append({
            "charge_id": cid,
            "category": r["category"],
            "recommended_action": r["recommended_action"],
            "policy_decision": pol_dec,
            "policy_reason": pol_reason,
            "approved_action": final_act,
        })

    conn.commit()
    conn.close()
    return policy_results
