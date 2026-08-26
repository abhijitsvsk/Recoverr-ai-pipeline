"""
Policy Engine for RecoverAI Payment Recovery Agent.
Deterministic validation engine that approves or blocks LLM recommendations
based strictly on POLICY.md rules. No AI/LLM calls.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Set, Optional

from db import get_connection
from models import Category, PaymentStatus, RecoveryAction
from timing import is_retry_backoff_satisfied, get_retry_backoff_seconds

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


def get_allowed_actions(
    category: str,
    amount_in_paise: int,
    retry_budget_remaining: int,
    high_value_threshold_paise: int,
    last_attempt_at: Optional[str] = None,
    ref_dt: Optional[datetime] = None,
) -> Set[str]:
    """
    Return the allowed actions set for a given category and context according to POLICY.md.
    Enforces retry backoff timing interval (15s in DEMO_MODE, 900s in Production).
    """
    is_high_value = amount_in_paise > high_value_threshold_paise
    backoff_satisfied = is_retry_backoff_satisfied(last_attempt_at, ref_dt)

    if category == Category.TEMPORARY.value:
        if retry_budget_remaining > 0 and backoff_satisfied:
            return {RecoveryAction.RETRY.value, RecoveryAction.SEND_RECOVERY_LINK.value}
        else:
            return {RecoveryAction.SEND_RECOVERY_LINK.value, RecoveryAction.ESCALATE.value}

    elif category == Category.PERMANENT.value:
        return {RecoveryAction.SEND_RECOVERY_LINK.value}

    elif category == Category.REPEATED_FAILURE.value:
        if is_high_value:
            return {RecoveryAction.STOP.value}
        return {RecoveryAction.ESCALATE.value}

    elif category == Category.UNKNOWN.value:
        if is_high_value:
            return {RecoveryAction.STOP.value}
        else:
            return {RecoveryAction.ESCALATE.value}

    return set()


def evaluate_policy(context: Dict[str, Any]) -> Tuple[str, str]:
    """
    Evaluates an LLM recommended action against deterministic POLICY.md rules.
    Returns (policy_decision, policy_reason) where policy_decision is 'APPROVED' or 'BLOCKED'.
    """
    category = context["category"]
    amount_in_paise = context["amount_in_paise"]
    recommended_action = context["recommended_action"]
    retry_budget_remaining = context["retry_budget_remaining"]
    last_attempt_at = context.get("last_attempt_at")
    ref_dt = context.get("ref_dt")
    high_value_thresh_inr = context.get("high_value_threshold_inr", get_high_value_threshold_inr())
    high_value_thresh_paise = high_value_thresh_inr * 100
    amt_inr = amount_in_paise / 100.0

    is_high_value = amount_in_paise > high_value_thresh_paise

    # 1. HARD OVERRIDE CHECK (Rule 1)
    if is_high_value and category in (Category.REPEATED_FAILURE.value, Category.UNKNOWN.value):
        if recommended_action != RecoveryAction.STOP.value:
            return (
                "BLOCKED",
                f"BLOCKED: Hard override — amount INR {amt_inr:,.2f} exceeds high-value threshold (INR {high_value_thresh_inr:,}) in '{category}' category. Action '{recommended_action}' is blocked; mandatory action is STOP."
            )
        else:
            return (
                "APPROVED",
                f"APPROVED: Hard override — STOP action mandatory and matched for high-value {category} payment (INR {amt_inr:,.2f})."
            )

    # 2. CATEGORY / CONTEXT ALLOWED ACTION CHECK (Rule 2)
    allowed_actions = get_allowed_actions(
        category,
        amount_in_paise,
        retry_budget_remaining,
        high_value_thresh_paise,
        last_attempt_at=last_attempt_at,
        ref_dt=ref_dt,
    )

    if recommended_action in allowed_actions:
        return (
            "APPROVED",
            f"APPROVED: '{recommended_action}' is in allowed actions {sorted(list(allowed_actions))} for category '{category}' (retry_budget_remaining={retry_budget_remaining}, high_value={is_high_value})."
        )
    else:
        return (
            "BLOCKED",
            f"BLOCKED: '{recommended_action}' is not in allowed actions {sorted(list(allowed_actions))} for category '{category}' (retry_budget_remaining={retry_budget_remaining}, high_value={is_high_value})."
        )


def process_policy_pipeline(db_path: str = "recover_ai.db") -> Dict[str, Any]:
    """
    Fetch all payments with status = 'RECOMMENDED'.
    Evaluate each against Policy Engine rules, update payment status to APPROVED or BLOCKED -> ESCALATED,
    and insert POLICY_DECISION audit_log rows.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, amount_in_paise, category, attempt_count, recommended_action, recommendation_reason, last_attempt_at 
        FROM payments 
        WHERE status = ? AND recommended_action IS NOT NULL;
        """,
        (PaymentStatus.RECOMMENDED.value,),
    )
    recommended_payments = cursor.fetchall()

    high_value_thresh_inr = get_high_value_threshold_inr()
    high_value_thresh_paise = high_value_thresh_inr * 100

    approved_count = 0
    blocked_count = 0
    approved_by_category = {}
    blocked_by_category = {}
    blocked_records = []
    now_str = datetime.now(timezone.utc).isoformat()

    for row in recommended_payments:
        payment_id = row["id"]
        amount_in_paise = row["amount_in_paise"]
        category = row["category"]
        attempt_count = row["attempt_count"]
        recommended_action = row["recommended_action"]
        last_attempt_at = row["last_attempt_at"]

        retries_used = max(0, attempt_count - 1)
        retry_budget_remaining = max(0, 2 - retries_used)

        context = {
            "payment_id": payment_id,
            "category": category,
            "attempt_count": attempt_count,
            "amount_in_paise": amount_in_paise,
            "recommended_action": recommended_action,
            "retry_budget_remaining": retry_budget_remaining,
            "last_attempt_at": last_attempt_at,
            "high_value_threshold_inr": high_value_thresh_inr,
        }

        decision, policy_reason = evaluate_policy(context)

        # Audit log insertion for POLICY_DECISION
        audit_id = f"aud_pol_{payment_id}"
        event_id = f"evt_pol_{payment_id}"

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
                "POLICY_DECISION",
                payment_id,
                attempt_count,
                now_str,
                category,
                recommended_action,
                decision,
                policy_reason,
                None,
                None,
                None,
                amount_in_paise,
            ),
        )

        if decision == "APPROVED":
            approved_count += 1
            approved_by_category[category] = approved_by_category.get(category, 0) + 1
            # RECOMMENDED -> APPROVED
            cursor.execute(
                """
                UPDATE payments
                SET status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (PaymentStatus.APPROVED.value, now_str, payment_id),
            )
        else:
            blocked_count += 1
            blocked_by_category[category] = blocked_by_category.get(category, 0) + 1
            blocked_records.append({
                "payment_id": payment_id,
                "category": category,
                "amount_in_paise": amount_in_paise,
                "amount_in_inr": amount_in_paise / 100.0,
                "recommended_action": recommended_action,
                "policy_reason": policy_reason,
            })

            # RECOMMENDED -> BLOCKED (Action Executor will process BLOCKED records to write ACTION_EXECUTED audit log and transition to ESCALATED)
            cursor.execute(
                """
                UPDATE payments
                SET status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (PaymentStatus.BLOCKED.value, now_str, payment_id),
            )

    conn.commit()
    conn.close()

    return {
        "processed_count": len(recommended_payments),
        "approved_count": approved_count,
        "blocked_count": blocked_count,
        "approved_by_category": approved_by_category,
        "blocked_by_category": blocked_by_category,
        "blocked_records": blocked_records,
    }
