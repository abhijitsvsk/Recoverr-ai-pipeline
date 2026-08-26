"""
Deterministic Policy Engine Module for Loop 2 Checkout Abandonment.
Enforces strict category-based allowed action rules and hard override checks.
100% separate from Loop 1 payment policy engine.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutCategory, CheckoutStatus, CheckoutRecoveryAction

# Narrow allowed actions set per category for Loop 2
ALLOWED_ACTIONS_BY_CATEGORY: Dict[str, set] = {
    CheckoutCategory.HIGH_VALUE_ABANDON.value: {CheckoutRecoveryAction.ESCALATE.value},
    CheckoutCategory.RECENT_ABANDON.value: {
        CheckoutRecoveryAction.SEND_CART_REMINDER.value,
        CheckoutRecoveryAction.SEND_DISCOUNT_NUDGE.value,
    },
    CheckoutCategory.REPEAT_ABANDONER.value: {CheckoutRecoveryAction.ESCALATE.value},
    CheckoutCategory.STALE_ABANDON.value: {CheckoutRecoveryAction.STOP.value},
    CheckoutCategory.UNKNOWN_ABANDON.value: {CheckoutRecoveryAction.ESCALATE.value},
}


def evaluate_checkout_policy(category: str, recommended_action: str) -> Tuple[str, str]:
    """
    Evaluates whether recommended_action is allowed for category.
    Returns (policy_decision, policy_reason) where policy_decision is 'APPROVED' or 'BLOCKED'.
    Validation order:
      1. Check HIGH_VALUE_ABANDON hard override.
      2. Check recommended_action against category allowed set.
    """
    # 1. Hard Override for HIGH_VALUE_ABANDON
    if category == CheckoutCategory.HIGH_VALUE_ABANDON.value:
        if recommended_action != CheckoutRecoveryAction.ESCALATE.value:
            return (
                "BLOCKED",
                f"BLOCKED: Category '{category}' hard override requires action 'ESCALATE', got '{recommended_action}'",
            )
        else:
            return (
                "APPROVED",
                f"APPROVED: Category '{category}' hard override action 'ESCALATE' is satisfied.",
            )

    # 2. Allowed Set Check
    allowed_set = ALLOWED_ACTIONS_BY_CATEGORY.get(category, set())
    allowed_list = sorted(list(allowed_set))

    if recommended_action in allowed_set:
        return (
            "APPROVED",
            f"APPROVED: Action '{recommended_action}' is in allowed actions {allowed_list} for category '{category}'",
        )
    else:
        return (
            "BLOCKED",
            f"BLOCKED: '{recommended_action}' is not in allowed actions {allowed_list} for category '{category}'",
        )


def process_checkout_policy_pipeline(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Batch evaluates policy for all checkouts in RECOMMENDED status.
    Transitions:
      RECOMMENDED -> APPROVED (if allowed)
      RECOMMENDED -> BLOCKED -> ESCALATED (if blocked, immediately routed to ESCALATED)
    Writes a POLICY_DECISION audit log row per evaluated checkout.
    """
    init_checkout_db(db_path)
    conn = get_checkout_connection(db_path)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, category, recommended_action, status
        FROM checkouts
        WHERE status = 'RECOMMENDED'
        ORDER BY id;
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    approved_count = 0
    blocked_count = 0
    processed_count = len(rows)

    now_iso = datetime.now(timezone.utc).isoformat()

    with conn:
        for r in rows:
            checkout_id = r["id"]
            category = r["category"]
            recommended_action = r["recommended_action"]
            cart_value_in_paise = r["cart_value_in_paise"]

            decision, reason = evaluate_checkout_policy(category, recommended_action)

            # Determine next status
            # If APPROVED -> APPROVED
            # If BLOCKED -> ESCALATED (disagreement gets human eyes, per specification)
            final_status = CheckoutStatus.APPROVED.value if decision == "APPROVED" else CheckoutStatus.ESCALATED.value

            if decision == "APPROVED":
                approved_count += 1
            else:
                blocked_count += 1

            # Update checkouts table
            cursor.execute(
                """
                UPDATE checkouts
                SET status = ?,
                    policy_decision = ?,
                    policy_reason = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (final_status, decision, reason, now_iso, checkout_id),
            )

            # Insert audit log entry
            log_id = f"log_pol_{checkout_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            event_id = f"evt_pol_{checkout_id}"

            cursor.execute(
                """
                INSERT INTO checkout_audit_log (
                    id, event_id, event_type, checkout_id, timestamp,
                    category, recommended_action, policy_decision, policy_reason, cart_value_in_paise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    log_id,
                    event_id,
                    "POLICY_DECISION",
                    checkout_id,
                    now_iso,
                    category,
                    recommended_action,
                    decision,
                    reason,
                    cart_value_in_paise,
                ),
            )

    conn.close()

    return {
        "processed_count": processed_count,
        "approved_count": approved_count,
        "blocked_count": blocked_count,
    }
