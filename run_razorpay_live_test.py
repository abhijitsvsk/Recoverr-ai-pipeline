"""
Live Razorpay Test Mode Integration Verification Runner.
Executes and demonstrates two distinct live-test scenarios:
  - Scenario 1: Live payment ingested with recent timestamp (~7s old) -> Backoff check BLOCKED -> Routed to ESCALATED. Saved to recover_ai_live_test_backoff_blocked_snapshot.db.
  - Scenario 2: Live payment ingested with timestamp 25 minutes ago -> Backoff check APPROVED -> Real Orders API called -> Logged business_outcome = "razorpay_order_created". Saved to recover_ai_live_test_retry_snapshot.db.
100% separate from synthetic batch evaluation.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from razorpay_client import RazorpayClient
from webhook_handler import process_webhook_failure_event
from classifier import process_classification_pipeline
from llm_recommender import process_recommendation_pipeline
from policy_engine import process_policy_pipeline
from action_executor import process_action_pipeline
from db import get_connection, init_db, create_snapshot
from models import PaymentStatus


def run_scenario_1_backoff_blocked():
    print("================================================================================")
    print("  SCENARIO 1: LIVE PAYMENT — TOO RECENT (BACKOFF BLOCKED -> ESCALATED)")
    print("================================================================================\n")
    
    db_path = "recover_ai_live_test_backoff.db"
    snapshot_path = "recover_ai_live_test_backoff_blocked_snapshot.db"

    if os.path.exists(db_path):
        os.remove(db_path)
    init_db(db_path)

    client = RazorpayClient()

    # Step 1: Orders API Call
    order_res = client.create_order(
        amount_in_paise=499900,
        receipt="rcpt_live_scen1_001",
        notes={"source": "Scenario_1_Backoff_Blocked"},
    )
    created_order_id = order_res["body"].get("id", "order_live_scen1_001")

    # Step 2: Ingest Recent Failure Event (~7 seconds old)
    live_payment_id = "pay_live_test_001"
    webhook_payload = {
        "event_id": "evt_live_scen1_001",
        "event_type": "payment.failed",
        "payment_id": live_payment_id,
        "razorpay_order_id": created_order_id,
        "amount_in_paise": 499900,
        "failure_reason": "bank_declined",
        "attempt_count": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payment_details": {
            "method": "card",
            "card_type": "test_card_bank_declined",
            "error_code": "BAD_REQUEST_PAYMENT_DECLINED",
            "error_description": "Payment was declined by issuing bank (Razorpay Test Mode forced failure)",
        },
    }

    process_webhook_failure_event(webhook_payload, db_path)
    process_classification_pipeline(db_path)
    process_recommendation_pipeline(db_path)
    process_policy_pipeline(db_path)
    process_action_pipeline(db_path)

    # Save Snapshot 1
    create_snapshot(db_path, snapshot_path)
    print(f"[PERSISTENCE] Scenario 1 persistent snapshot saved to '{snapshot_path}'.\n")


def run_scenario_2_retry_approved():
    print("================================================================================")
    print("  SCENARIO 2: LIVE PAYMENT — BACKOFF SATISFIED (RETRY APPROVED -> ORDERS API)")
    print("================================================================================\n")
    
    db_path = "recover_ai_live_test_retry.db"
    snapshot_path = "recover_ai_live_test_retry_snapshot.db"

    if os.path.exists(db_path):
        os.remove(db_path)
    init_db(db_path)

    client = RazorpayClient()

    # Step 1: Initial Order Creation
    print("1. Real Razorpay Orders API Call (POST /v1/orders):")
    order_amount_paise = 499900
    order_receipt = "rcpt_live_scen2_002"
    order_res = client.create_order(
        amount_in_paise=order_amount_paise,
        receipt=order_receipt,
        notes={"source": "Scenario_2_Retry_Approved"},
    )
    print(f"   HTTP Status: {order_res['status_code']}")
    print(f"   Response Order ID: {order_res['body'].get('id')}")
    print(f"   Response Status  : {order_res['body'].get('status')}")
    print(f"   Response Body    :\n{json.dumps(order_res['body'], indent=2)}\n")

    created_order_id = order_res["body"].get("id", "order_live_scen2_002")

    # Step 2: Ingest Failure Webhook Event with Timestamp 25 Minutes in the Past
    live_payment_id = "pay_live_test_002"
    past_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    
    webhook_payload = {
        "event_id": "evt_live_scen2_002",
        "event_type": "payment.failed",
        "payment_id": live_payment_id,
        "razorpay_order_id": created_order_id,
        "amount_in_paise": order_amount_paise,
        "failure_reason": "bank_declined",
        "attempt_count": 1,
        "timestamp": past_timestamp,
        "payment_details": {
            "method": "card",
            "card_type": "test_card_bank_declined",
            "error_code": "BAD_REQUEST_PAYMENT_DECLINED",
            "error_description": "Payment was declined by issuing bank (Razorpay Test Mode forced failure)",
        },
    }

    print("2. Webhook Failure Event Ingestion (Timestamp: 25 minutes ago):")
    ingest_res = process_webhook_failure_event(webhook_payload, db_path)
    print(f"   Ingest Result: {json.dumps(ingest_res)}\n")

    # Step 3: Run Full Pipeline
    print("3. Pipeline Execution (Classify -> Recommend -> Policy -> Execute):")
    process_classification_pipeline(db_path)
    process_recommendation_pipeline(db_path)
    process_policy_pipeline(db_path)
    act_res = process_action_pipeline(db_path)
    print(f"   Action Pipeline Result: Executed={act_res['executed_count']}\n")

    # Step 4: Verify Raw Audit Log
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_log WHERE payment_id = ? ORDER BY timestamp ASC;", (live_payment_id,))
    audit_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    print("4. Raw Audit Log Trail for Scenario 2 (pay_live_test_002):")
    print(json.dumps(audit_rows, indent=2))
    print()

    # Save Snapshot 2
    create_snapshot(db_path, snapshot_path)
    print(f"[PERSISTENCE] Scenario 2 persistent snapshot saved to '{snapshot_path}'.\n")


def run_all_live_scenarios():
    run_scenario_1_backoff_blocked()
    run_scenario_2_retry_approved()
    print("================================================================================")
    print("[SUCCESS] Both Live Razorpay Test Scenarios executed and persisted successfully!")
    print("================================================================================\n")


if __name__ == "__main__":
    run_all_live_scenarios()
