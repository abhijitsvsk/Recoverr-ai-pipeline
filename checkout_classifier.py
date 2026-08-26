"""
Deterministic Failure Classifier for Checkout Abandonment Loop 2.
Implements category lookup rules with strict priority ordering.
100% separate from Loop 1 payment classifier.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from checkout_db import get_checkout_connection
from checkout_models import CheckoutCategory, CheckoutStatus

CHECKOUT_HIGH_VALUE_THRESHOLD_INR = 10000
CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE = CHECKOUT_HIGH_VALUE_THRESHOLD_INR * 100

RECENT_REASONS = {
    "inactivity_timeout_15m",
    "exit_intent_popup",
    "tab_closed_active_cart",
}

STALE_REASONS = {
    "session_expired_60m",
    "inactivity_timeout_24h",
    "abandoned_cart_reminder_unopened",
}


def classify_checkout(
    cart_value_in_paise: int,
    abandon_count: int,
    customer_abandon_reason: str,
    abandoned_at: str,
) -> CheckoutCategory:
    """
    Classify checkout abandonment deterministically based on rule priority order:
    Rule 1: cart_value_in_paise > threshold (1,000,000 paise / INR 10,000) -> HIGH_VALUE_ABANDON (always wins).
    Rule 2: abandon_count >= 2 -> REPEAT_ABANDONER.
    Rule 3: customer_abandon_reason signal lookup:
            - Recent reasons -> RECENT_ABANDON
            - Stale reasons  -> STALE_ABANDON
    """
    # Priority Rule 1: High Value Threshold Check
    if cart_value_in_paise > CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE:
        return CheckoutCategory.HIGH_VALUE_ABANDON

    # Priority Rule 2: Repeat Abandoner Check
    if abandon_count >= 2:
        return CheckoutCategory.REPEAT_ABANDONER

    # Priority Rule 3: Reason / Signal Lookup Check
    reason_clean = customer_abandon_reason.strip().lower() if customer_abandon_reason else ""

    if reason_clean in RECENT_REASONS:
        return CheckoutCategory.RECENT_ABANDON
    elif reason_clean in STALE_REASONS:
        return CheckoutCategory.STALE_ABANDON
    else:
        # Safe fallback for unrecognized / unmapped abandon reasons, matching Loop 1's UNKNOWN pattern
        return CheckoutCategory.UNKNOWN_ABANDON


def process_checkout_classification_pipeline(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Fetch all checkouts with status = 'ABANDONED' and category IS NULL.
    Classify each checkout, update status to 'CLASSIFIED', and insert CLASSIFIED audit_log entry.
    Returns summary statistics.
    """
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, cart_value_in_paise, customer_abandon_reason, expected_category, abandon_count, abandoned_at 
        FROM checkouts 
        WHERE status = ? AND category IS NULL;
        """,
        (CheckoutStatus.ABANDONED.value,),
    )
    unclassified_checkouts = cursor.fetchall()

    classified_count = 0
    now_str = datetime.now(timezone.utc).isoformat()

    with conn:
        for row in unclassified_checkouts:
            checkout_id = row["id"]
            cart_value_in_paise = row["cart_value_in_paise"]
            customer_abandon_reason = row["customer_abandon_reason"]
            abandon_count = row["abandon_count"]
            abandoned_at = row["abandoned_at"]

            assigned_category = classify_checkout(
                cart_value_in_paise=cart_value_in_paise,
                abandon_count=abandon_count,
                customer_abandon_reason=customer_abandon_reason,
                abandoned_at=abandoned_at,
            ).value

            # Update checkouts table: set category and transition status ABANDONED -> CLASSIFIED
            cursor.execute(
                """
                UPDATE checkouts
                SET category = ?, status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (assigned_category, CheckoutStatus.CLASSIFIED.value, now_str, checkout_id),
            )

            # Insert checkout_audit_log row for CLASSIFIED event
            audit_id = f"aud_class_{checkout_id}"
            event_id = f"evt_class_{checkout_id}"

            cursor.execute(
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
                    "CLASSIFIED",
                    checkout_id,
                    now_str,
                    assigned_category,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    cart_value_in_paise,
                ),
            )
            classified_count += 1

    conn.close()

    return {
        "processed_count": len(unclassified_checkouts),
        "classified_count": classified_count,
    }
