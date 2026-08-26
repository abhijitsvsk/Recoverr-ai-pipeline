"""
Deterministic Failure Classifier for RecoverAI Payment Recovery Agent.
Implements category lookup rules according to AGENTS.md and POLICY.md.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from db import get_connection
from models import Category, PaymentStatus

TEMPORARY_REASONS = {"network_error", "gateway_error", "bank_declined"}
PERMANENT_REASONS = {"insufficient_funds", "card_expired", "payment_cancelled"}


def classify_failure(failure_reason: str, attempt_count: int) -> Category:
    """
    Classify payment failure deterministically based on failure_reason and attempt_count.
    Rule 1: attempt_count >= 3 -> REPEATED_FAILURE (attempt count overrides reason mapping).
    Rule 2: Fixed lookup table for attempt_count < 3:
      - network_error, gateway_error, bank_declined -> TEMPORARY
      - insufficient_funds, card_expired, payment_cancelled -> PERMANENT
      - All unrecognized/unmapped codes -> UNKNOWN
    """
    if attempt_count >= 3:
        return Category.REPEATED_FAILURE

    reason_clean = failure_reason.strip().lower() if failure_reason else ""

    if reason_clean in TEMPORARY_REASONS:
        return Category.TEMPORARY
    elif reason_clean in PERMANENT_REASONS:
        return Category.PERMANENT
    else:
        return Category.UNKNOWN


def process_classification_pipeline(db_path: str = "recover_ai.db") -> int:
    """
    Fetch all payments with status = 'FAILED' and category IS NULL.
    Classify each payment, update payment status to 'CLASSIFIED', and write CLASSIFIED audit_log entry.
    Returns count of classified payments.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, amount_in_paise, failure_reason, attempt_count 
        FROM payments 
        WHERE status = ? AND category IS NULL;
        """,
        (PaymentStatus.FAILED.value,),
    )
    unclassified_payments = cursor.fetchall()

    classified_count = 0
    now_str = datetime.now(timezone.utc).isoformat()

    with conn:
        for row in unclassified_payments:
            payment_id = row["id"]
            amount_in_paise = row["amount_in_paise"]
            failure_reason = row["failure_reason"]
            attempt_count = row["attempt_count"]

            assigned_category = classify_failure(failure_reason, attempt_count).value

            # Update payments table: set category and transition status FAILED -> CLASSIFIED
            cursor.execute(
                """
                UPDATE payments
                SET category = ?, status = ?, updated_at = ?
                WHERE id = ?;
                """,
                (assigned_category, PaymentStatus.CLASSIFIED.value, now_str, payment_id),
            )

            # Insert audit_log row for CLASSIFIED event
            audit_id = f"aud_class_{payment_id}"
            event_id = f"evt_class_{payment_id}"

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
                    "CLASSIFIED",
                    payment_id,
                    attempt_count,
                    now_str,
                    assigned_category,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    amount_in_paise,
                ),
            )
            classified_count += 1

    conn.close()
    return classified_count
