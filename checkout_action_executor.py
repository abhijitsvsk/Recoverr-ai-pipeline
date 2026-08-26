"""
Action Executor Module for Loop 2 Checkout Abandonment Recovery.
Executes simulated recovery actions (SEND_CART_REMINDER, SEND_DISCOUNT_NUDGE, ESCALATE, STOP),
enforces idempotency protection, updates database statuses, and records immutable ACTION_EXECUTED audit log rows.
100% separate from Loop 1 payment action executor.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutStatus, CheckoutRecoveryAction


def execute_single_checkout_action(checkout: Dict[str, Any], conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Executes simulated action for a single checkout.
    Checks idempotency before executing.
    Returns dictionary with execution details or skip reason.
    """
    checkout_id = checkout["id"]
    event_id = f"evt_act_{checkout_id}"
    cart_value_in_paise = checkout["cart_value_in_paise"]
    category = checkout["category"]
    recommended_action = checkout["recommended_action"]
    policy_decision = checkout.get("policy_decision")
    policy_reason = checkout.get("policy_reason")
    current_status = checkout["status"]

    cursor = conn.cursor()

    # Idempotency Check
    cursor.execute(
        "SELECT 1 FROM checkout_idempotency WHERE event_id = ?;",
        (event_id,)
    )
    if cursor.fetchone():
        return {
            "checkout_id": checkout_id,
            "status": "skipped",
            "reason": f"Idempotency lock exists for event_id '{event_id}'",
        }

    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert idempotency record BEFORE acting
    cursor.execute(
        """
        INSERT INTO checkout_idempotency (event_id, checkout_id, processed_at)
        VALUES (?, ?, ?);
        """,
        (event_id, checkout_id, now_iso),
    )

    # Determine action to take
    # If APPROVED: action_taken = recommended_action
    # If BLOCKED / ESCALATED: action_taken = ESCALATE
    if current_status == CheckoutStatus.APPROVED.value:
        action_taken = recommended_action
    else:
        action_taken = CheckoutRecoveryAction.ESCALATE.value

    # Map action execution parameters
    if action_taken == CheckoutRecoveryAction.SEND_CART_REMINDER.value:
        execution_result = "reminder_sent"
        business_outcome = "reminder_sent"
        final_status = CheckoutStatus.SUCCEEDED.value

    elif action_taken == CheckoutRecoveryAction.SEND_DISCOUNT_NUDGE.value:
        execution_result = "nudge_sent"
        business_outcome = "nudge_sent"
        final_status = CheckoutStatus.SUCCEEDED.value

    elif action_taken == CheckoutRecoveryAction.ESCALATE.value:
        execution_result = "logged"
        business_outcome = "escalated"
        final_status = CheckoutStatus.ESCALATED.value

    elif action_taken == CheckoutRecoveryAction.STOP.value:
        execution_result = "no_action"
        business_outcome = "unresolved"
        final_status = CheckoutStatus.STOPPED.value

    else:
        execution_result = "unknown_action"
        business_outcome = "unresolved"
        final_status = CheckoutStatus.FAILED_EXECUTION.value

    # Update checkouts table
    cursor.execute(
        """
        UPDATE checkouts
        SET status = ?,
            updated_at = ?
        WHERE id = ?;
        """,
        (final_status, now_iso, checkout_id),
    )

    # Insert ACTION_EXECUTED audit log row
    log_id = f"log_act_{checkout_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    cursor.execute(
        """
        INSERT INTO checkout_audit_log (
            id, event_id, event_type, checkout_id, timestamp,
            category, recommended_action, policy_decision, policy_reason,
            action_taken, execution_result, business_outcome, cart_value_in_paise
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            log_id,
            event_id,
            "ACTION_EXECUTED",
            checkout_id,
            now_iso,
            category,
            recommended_action,
            policy_decision,
            policy_reason,
            action_taken,
            execution_result,
            business_outcome,
            cart_value_in_paise,
        ),
    )

    return {
        "checkout_id": checkout_id,
        "status": "executed",
        "action_taken": action_taken,
        "execution_result": execution_result,
        "business_outcome": business_outcome,
        "final_status": final_status,
    }


def process_checkout_execution_pipeline(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Processes all checkouts at status APPROVED or ESCALATED.
    Ensures 100% of checkouts reach an ACTION_EXECUTED audit log event.
    Returns execution summary.
    """
    init_checkout_db(db_path)
    conn = get_checkout_connection(db_path)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, category, recommended_action, 
               policy_decision, policy_reason, status
        FROM checkouts
        WHERE status IN ('APPROVED', 'ESCALATED')
        ORDER BY id;
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    executed_count = 0
    skipped_count = 0
    action_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}

    with conn:
        for r in rows:
            res = execute_single_checkout_action(r, conn)
            if res["status"] == "executed":
                executed_count += 1
                act = res["action_taken"]
                st = res["final_status"]
                action_counts[act] = action_counts.get(act, 0) + 1
                status_counts[st] = status_counts.get(st, 0) + 1
            else:
                skipped_count += 1

    conn.close()

    return {
        "processed_count": len(rows),
        "executed_count": executed_count,
        "skipped_count": skipped_count,
        "action_counts": action_counts,
        "status_counts": status_counts,
    }
