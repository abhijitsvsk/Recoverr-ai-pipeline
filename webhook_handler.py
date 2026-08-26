"""
Minimal Webhook Handler for Razorpay payment.failed Ingestion.
Enforces idempotency via event_id + payment_id and triggers pipeline ingestion.
100% separate from synthetic batch evaluation.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any

from db import get_connection
from models import PaymentStatus

def process_webhook_failure_event(payload: Dict[str, Any], db_path: str = "recover_ai.db") -> Dict[str, Any]:
    """
    Ingest a payment.failed webhook event payload into recover_ai.db.
    Enforces idempotency (event_id + payment_id) per AGENTS.md Rule 8.
    """
    event_id = payload.get("event_id")
    payment_id = payload.get("payment_id")
    amount_in_paise = payload.get("amount_in_paise")
    failure_reason = payload.get("failure_reason", "network_error")
    attempt_count = payload.get("attempt_count", 1)
    razorpay_order_id = payload.get("razorpay_order_id")

    if not event_id or not payment_id or amount_in_paise is None:
        return {"status": "rejected", "reason": "missing_required_fields"}

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Idempotency Check (AGENTS.md Rule 8)
    cursor.execute("SELECT processed_at FROM idempotency WHERE event_id = ?;", (event_id,))
    idem_row = cursor.fetchone()
    if idem_row:
        conn.close()
        return {"status": "ignored_duplicate", "event_id": event_id, "payment_id": payment_id}

    now_str = datetime.now(timezone.utc).isoformat()
    abandoned_at_str = payload.get("timestamp", now_str)

    with conn:
        cursor = conn.cursor()
        # 1. Insert new payment row into payments table first (foreign key target)
        cursor.execute(
            """
            INSERT INTO payments (
                id, amount_in_paise, failure_reason, ground_truth_category, category,
                attempt_count, last_attempt_at, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                payment_id,
                amount_in_paise,
                failure_reason,
                "TEMPORARY",  # default ground truth for live test
                None,  # category assigned by classifier
                attempt_count,
                abandoned_at_str,
                PaymentStatus.FAILED.value,
                now_str,
                now_str,
            ),
        )

        # 2. Record idempotency event
        cursor.execute(
            "INSERT INTO idempotency (event_id, payment_id, processed_at) VALUES (?, ?, ?);",
            (event_id, payment_id, now_str),
        )

        # Insert PAYMENT_FAILED audit_log entry
        audit_id = f"aud_fail_{payment_id}"
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
                "PAYMENT_FAILED",
                payment_id,
                attempt_count,
                now_str,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                amount_in_paise,
            ),
        )

    conn.close()
    return {
        "status": "ingested",
        "event_id": event_id,
        "payment_id": payment_id,
        "razorpay_order_id": razorpay_order_id,
    }
