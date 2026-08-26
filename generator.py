"""
Synthetic Data Generator for RecoverAI Payment Recovery Agent Foundation.
Generates reproducible payment records, initial audit log entries, and idempotency tracking.
"""

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any, Optional

from models import Category, PaymentStatus, Payment, AuditLogEntry, IdempotencyRecord
from db import get_connection, init_db

# Ground truth category distribution for exactly 100 records
DISTRIBUTION = [
    (Category.TEMPORARY.value, 40),
    (Category.PERMANENT.value, 25),
    (Category.REPEATED_FAILURE.value, 20),
    (Category.UNKNOWN.value, 15),
]

FAILURE_REASONS = {
    Category.TEMPORARY.value: ["network_error", "gateway_error", "bank_declined"],
    Category.PERMANENT.value: ["insufficient_funds", "card_expired", "payment_cancelled"],
    Category.REPEATED_FAILURE.value: [
        "bank_declined",
        "network_error",
        "gateway_error",
        "insufficient_funds",
        "card_expired",
    ],
    Category.UNKNOWN.value: [
        "unmapped_error_88",
        "processor_unknown",
        "gateway_response_unknown",
        "invalid_response_code",
        "unexpected_failure",
    ],
}


def generate_dataset(seed: int) -> Tuple[List[Payment], List[AuditLogEntry], List[IdempotencyRecord]]:
    """
    Generate 100 synthetic failed payment records reproducibly based on an integer seed.
    Returns (payments, audit_entries, idempotency_records).
    """
    rng = random.Random(seed)

    # Build exact distribution list of ground_truth_category
    categories = []
    for cat_name, count in DISTRIBUTION:
        categories.extend([cat_name] * count)
    
    # Shuffle categories deterministically using the seeded RNG
    rng.shuffle(categories)

    payments: List[Payment] = []
    audit_entries: List[AuditLogEntry] = []
    idempotency_records: List[IdempotencyRecord] = []

    # Base reference timestamp for deterministic generation
    base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

    for idx, ground_truth_cat in enumerate(categories, start=1):
        payment_id = f"pay_{seed}_{idx:03d}"
        event_id = f"evt_fail_{seed}_{idx:03d}"

        # Select failure reason from mapped choices
        failure_reason = rng.choice(FAILURE_REASONS[ground_truth_cat])

        # Generate realistic amount in paise (e.g., ₹100 to ₹25,000)
        # Mix in amounts > ₹10,000 (1,000,000 paise) for high-value threshold testing
        amount_in_inr = rng.choice([150, 499, 999, 1499, 2999, 5000, 8500, 12000, 15000, 22500])
        amount_in_paise = amount_in_inr * 100

        # Determine attempt_count and timestamps
        if ground_truth_cat == Category.TEMPORARY.value:
            attempt_count = rng.choice([1, 2])
        elif ground_truth_cat == Category.PERMANENT.value:
            attempt_count = rng.choice([1, 2])
        elif ground_truth_cat == Category.REPEATED_FAILURE.value:
            attempt_count = rng.choice([3, 4, 5])
        else:  # UNKNOWN
            attempt_count = rng.choice([1, 2])

        # Timestamps
        days_ago = rng.randint(1, 10)
        created_dt = base_time - timedelta(days=days_ago, minutes=rng.randint(0, 300))
        
        if attempt_count > 1:
            last_attempt_dt = created_dt + timedelta(hours=rng.randint(1, 24 * days_ago))
        else:
            last_attempt_dt = created_dt

        created_at_str = created_dt.isoformat()
        last_attempt_at_str = last_attempt_dt.isoformat()
        updated_at_str = last_attempt_at_str

        # Create Payment object
        # NOTE: category stays None / NULL initially, status stays FAILED
        payment = Payment(
            id=payment_id,
            amount_in_paise=amount_in_paise,
            failure_reason=failure_reason,
            ground_truth_category=ground_truth_cat,
            category=None,
            status=PaymentStatus.FAILED.value,
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at_str,
            created_at=created_at_str,
            updated_at=updated_at_str,
        )
        payments.append(payment)

        # Initial Audit Log entry for the failure event
        audit_id = f"aud_{seed}_{idx:03d}"
        audit_entry = AuditLogEntry(
            id=audit_id,
            event_id=event_id,
            event_type="PAYMENT_FAILED",
            payment_id=payment_id,
            attempt_number=attempt_count,
            timestamp=last_attempt_at_str,
            amount_in_paise=amount_in_paise,
            category=None,
            recommended_action=None,
            policy_decision=None,
            policy_reason=None,
            action_taken=None,
            execution_result=None,
            business_outcome=None,
        )
        audit_entries.append(audit_entry)

        # Idempotency record for the failure event
        idempotency_record = IdempotencyRecord(
            event_id=event_id,
            payment_id=payment_id,
            processed_at=last_attempt_at_str,
        )
        idempotency_records.append(idempotency_record)

    return payments, audit_entries, idempotency_records


def save_dataset_to_db(
    seed: int,
    payments: List[Payment],
    audit_entries: List[AuditLogEntry],
    idempotency_records: List[IdempotencyRecord],
    db_path: str = "recover_ai.db",
) -> None:
    """Save generated dataset to SQLite database."""
    conn = get_connection(db_path)
    with conn:
        # Drop tables to bypass append-only triggers cleanly during fresh database re-seeding
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update;")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete;")
        conn.execute("DROP TABLE IF EXISTS audit_log;")
        conn.execute("DROP TABLE IF EXISTS idempotency;")
        conn.execute("DROP TABLE IF EXISTS payments;")
        conn.execute("DROP TABLE IF EXISTS dataset_metadata;")

    conn.close()

    # Re-create tables and append-only triggers afresh
    init_db(db_path)

    conn = get_connection(db_path)
    with conn:
        # Insert payments
        conn.executemany(
            """
            INSERT INTO payments (
                id, amount_in_paise, failure_reason, ground_truth_category,
                category, status, attempt_count, last_attempt_at, created_at, updated_at,
                recommended_action, recommendation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                (
                    p.id,
                    p.amount_in_paise,
                    p.failure_reason,
                    p.ground_truth_category,
                    p.category,
                    p.status,
                    p.attempt_count,
                    p.last_attempt_at,
                    p.created_at,
                    p.updated_at,
                    p.recommended_action,
                    p.recommendation_reason,
                )
                for p in payments
            ],
        )

        # Insert initial audit log entries
        conn.executemany(
            """
            INSERT INTO audit_log (
                id, event_id, event_type, payment_id, attempt_number, timestamp,
                category, recommended_action, policy_decision, policy_reason,
                action_taken, execution_result, business_outcome, amount_in_paise
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                (
                    a.id,
                    a.event_id,
                    a.event_type,
                    a.payment_id,
                    a.attempt_number,
                    a.timestamp,
                    a.category,
                    a.recommended_action,
                    a.policy_decision,
                    a.policy_reason,
                    a.action_taken,
                    a.execution_result,
                    a.business_outcome,
                    a.amount_in_paise,
                )
                for a in audit_entries
            ],
        )

        # Insert idempotency records
        conn.executemany(
            """
            INSERT INTO idempotency (event_id, payment_id, processed_at) VALUES (?, ?, ?);
            """,
            [(i.event_id, i.payment_id, i.processed_at) for i in idempotency_records],
        )

        # Record dataset metadata
        conn.execute(
            """
            INSERT INTO dataset_metadata (seed, record_count, generated_at)
            VALUES (?, ?, ?);
            """,
            (seed, len(payments), datetime.now(timezone.utc).isoformat()),
        )

    conn.close()
