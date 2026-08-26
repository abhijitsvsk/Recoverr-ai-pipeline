"""
Synthetic Data Generator for Checkout Abandonment Loop 2 Foundation.
Generates reproducible checkout abandonment records, audit log entries, and idempotency tracking.
100% separate from Loop 1 payment generator.
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any, Optional

from checkout_models import (
    CheckoutCategory,
    CheckoutStatus,
    Checkout,
    CheckoutAuditLogEntry,
    CheckoutIdempotencyRecord,
)
from checkout_db import get_checkout_connection, init_checkout_db

# Reusing ₹10,000 threshold (1,000,000 paise) from loop 1's HIGH_VALUE_THRESHOLD_INR config to maintain
# a consistent risk boundary across payment and checkout recovery loops.
CHECKOUT_HIGH_VALUE_THRESHOLD_INR = 10000
CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE = CHECKOUT_HIGH_VALUE_THRESHOLD_INR * 100

# Distribution of ground truth categories for exactly 100 checkout records
CHECKOUT_DISTRIBUTION = [
    (CheckoutCategory.RECENT_ABANDON.value, 45),
    (CheckoutCategory.STALE_ABANDON.value, 20),
    (CheckoutCategory.REPEAT_ABANDONER.value, 20),
    (CheckoutCategory.HIGH_VALUE_ABANDON.value, 15),
]

ABANDON_REASONS = {
    CheckoutCategory.RECENT_ABANDON.value: [
        "inactivity_timeout_15m",
        "exit_intent_popup",
        "tab_closed_active_cart",
    ],
    CheckoutCategory.STALE_ABANDON.value: [
        "session_expired_60m",
        "inactivity_timeout_24h",
        "abandoned_cart_reminder_unopened",
    ],
    CheckoutCategory.REPEAT_ABANDONER.value: [
        "multi_session_abandon",
        "repeat_checkout_dropoff",
        "saved_cart_expired",
    ],
    CheckoutCategory.HIGH_VALUE_ABANDON.value: [
        "high_value_checkout_idle",
        "payment_step_backtrack",
        "premium_cart_timeout",
    ],
}


def generate_checkout_dataset(
    seed: int,
) -> Tuple[List[Checkout], List[CheckoutAuditLogEntry], List[CheckoutIdempotencyRecord]]:
    """
    Generate 100 synthetic abandoned checkout records reproducibly based on an integer seed.
    Enforces strict mutual exclusivity between HIGH_VALUE_ABANDON and other categories.
    Returns (checkouts, audit_entries, idempotency_records).
    """
    rng = random.Random(seed)

    # Build exact distribution list of expected_category
    categories = []
    for cat_name, count in CHECKOUT_DISTRIBUTION:
        categories.extend([cat_name] * count)

    # Shuffle categories deterministically
    rng.shuffle(categories)

    checkouts: List[Checkout] = []
    audit_entries: List[CheckoutAuditLogEntry] = []
    idempotency_records: List[CheckoutIdempotencyRecord] = []

    # Reference timestamp for generation
    base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    for idx, expected_cat in enumerate(categories, start=1):
        checkout_id = f"chk_{seed}_{idx:03d}"
        event_id = f"evt_abnd_{seed}_{idx:03d}"

        # Raw customer abandon reason signal
        abandon_reason = rng.choice(ABANDON_REASONS[expected_cat])

        # Determine abandon_count and cart_value_in_paise based on category rules
        if expected_cat == CheckoutCategory.RECENT_ABANDON.value:
            abandon_count = 1
            cart_value_inr = rng.choice([199, 499, 999, 1499, 2999, 4999, 7999, 9500])
            cart_value_in_paise = cart_value_inr * 100
            hours_ago = rng.randint(1, 3)

        elif expected_cat == CheckoutCategory.STALE_ABANDON.value:
            abandon_count = 1
            cart_value_inr = rng.choice([299, 599, 1299, 2499, 3999, 6999, 8999])
            cart_value_in_paise = cart_value_inr * 100
            hours_ago = rng.randint(48, 120)  # Abandoned 2 to 5 days ago

        elif expected_cat == CheckoutCategory.REPEAT_ABANDONER.value:
            abandon_count = rng.choice([2, 3, 4])  # strictly >= 2
            cart_value_inr = rng.choice([499, 999, 1999, 3499, 5999, 8499, 9990])
            cart_value_in_paise = cart_value_inr * 100
            hours_ago = rng.randint(4, 48)

        else:  # HIGH_VALUE_ABANDON
            abandon_count = rng.choice([1, 2, 3])
            cart_value_inr = rng.choice([12000, 15000, 22000, 35000, 50000, 75000])
            cart_value_in_paise = cart_value_inr * 100
            hours_ago = rng.randint(1, 48)

        # EXPLICIT MUTUAL EXCLUSIVITY CODE GUARD:
        # Enforce that only HIGH_VALUE_ABANDON records exceed threshold (1,000,000 paise).
        if expected_cat != CheckoutCategory.HIGH_VALUE_ABANDON.value:
            if cart_value_in_paise > CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE:
                raise ValueError(
                    f"Mutual exclusivity guard failed for record {checkout_id}: "
                    f"Category '{expected_cat}' generated cart value paise {cart_value_in_paise} > threshold {CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE}."
                )
        else:
            if cart_value_in_paise <= CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE:
                raise ValueError(
                    f"Mutual exclusivity guard failed for record {checkout_id}: "
                    f"Category '{expected_cat}' generated cart value paise {cart_value_in_paise} <= threshold {CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE}."
                )

        abandoned_dt = base_time - timedelta(hours=hours_ago, minutes=rng.randint(0, 59))
        abandoned_at_str = abandoned_dt.isoformat()
        created_at_str = (abandoned_dt - timedelta(minutes=15)).isoformat()
        updated_at_str = abandoned_at_str

        # Create Checkout object (category stays None / NULL, status stays ABANDONED)
        checkout = Checkout(
            id=checkout_id,
            cart_value_in_paise=cart_value_in_paise,
            customer_abandon_reason=abandon_reason,
            expected_category=expected_cat,
            category=None,
            status=CheckoutStatus.ABANDONED.value,
            abandon_count=abandon_count,
            abandoned_at=abandoned_at_str,
            created_at=created_at_str,
            updated_at=updated_at_str,
        )
        checkouts.append(checkout)

        # Initial Audit Log entry for the CHECKOUT_ABANDONED event
        audit_id = f"aud_abnd_{seed}_{idx:03d}"
        audit_entry = CheckoutAuditLogEntry(
            id=audit_id,
            event_id=event_id,
            event_type="CHECKOUT_ABANDONED",
            checkout_id=checkout_id,
            timestamp=abandoned_at_str,
            cart_value_in_paise=cart_value_in_paise,
            category=None,
            recommended_action=None,
            policy_decision=None,
            policy_reason=None,
            action_taken=None,
            execution_result=None,
            business_outcome=None,
        )
        audit_entries.append(audit_entry)

        # Idempotency record for the abandonment event
        idempotency_record = CheckoutIdempotencyRecord(
            event_id=event_id,
            checkout_id=checkout_id,
            processed_at=abandoned_at_str,
        )
        idempotency_records.append(idempotency_record)

    return checkouts, audit_entries, idempotency_records


def save_checkout_dataset_to_db(
    seed: int,
    checkouts: List[Checkout],
    audit_entries: List[CheckoutAuditLogEntry],
    idempotency_records: List[CheckoutIdempotencyRecord],
    db_path: str = "checkout_recovery.db",
) -> None:
    """Save generated checkout dataset to checkout_recovery.db SQLite database."""
    conn = get_checkout_connection(db_path)
    with conn:
        # Drop triggers & tables for clean re-seeding without append-only errors
        conn.execute("DROP TRIGGER IF EXISTS checkout_audit_log_no_update;")
        conn.execute("DROP TRIGGER IF EXISTS checkout_audit_log_no_delete;")
        conn.execute("DROP TABLE IF EXISTS checkout_audit_log;")
        conn.execute("DROP TABLE IF EXISTS checkout_idempotency;")
        conn.execute("DROP TABLE IF EXISTS checkouts;")
        conn.execute("DROP TABLE IF EXISTS checkout_dataset_metadata;")

    conn.close()

    # Re-initialize schema and append-only triggers
    init_checkout_db(db_path)

    conn = get_checkout_connection(db_path)
    with conn:
        # Insert checkouts
        conn.executemany(
            """
            INSERT INTO checkouts (
                id, cart_value_in_paise, customer_abandon_reason, expected_category,
                category, status, abandon_count, abandoned_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                (
                    c.id,
                    c.cart_value_in_paise,
                    c.customer_abandon_reason,
                    c.expected_category,
                    c.category,
                    c.status,
                    c.abandon_count,
                    c.abandoned_at,
                    c.created_at,
                    c.updated_at,
                )
                for c in checkouts
            ],
        )

        # Insert audit log entries
        conn.executemany(
            """
            INSERT INTO checkout_audit_log (
                id, event_id, event_type, checkout_id, timestamp,
                category, recommended_action, policy_decision, policy_reason,
                action_taken, execution_result, business_outcome, cart_value_in_paise
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                (
                    a.id,
                    a.event_id,
                    a.event_type,
                    a.checkout_id,
                    a.timestamp,
                    a.category,
                    a.recommended_action,
                    a.policy_decision,
                    a.policy_reason,
                    a.action_taken,
                    a.execution_result,
                    a.business_outcome,
                    a.cart_value_in_paise,
                )
                for a in audit_entries
            ],
        )

        # Insert idempotency records
        conn.executemany(
            """
            INSERT INTO checkout_idempotency (event_id, checkout_id, processed_at) VALUES (?, ?, ?);
            """,
            [(i.event_id, i.checkout_id, i.processed_at) for i in idempotency_records],
        )

        # Record dataset metadata
        conn.execute(
            """
            INSERT INTO checkout_dataset_metadata (seed, record_count, generated_at)
            VALUES (?, ?, ?);
            """,
            (seed, len(checkouts), datetime.now(timezone.utc).isoformat()),
        )

    conn.close()
