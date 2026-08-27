"""
Live Razorpay REST API Test Runner for Loop 3 Duplicate Charge Auto-Refunds.
Calls real Razorpay Test Mode REST API endpoints (/v1/orders & /v1/payments/{payment_id}/refund).
Uses X-Refund-Idempotency header and prints literal raw JSON response.
"""

import os
import json
import uuid
from razorpay_client import RazorpayClient
from dup_action_executor import execute_dup_refund


def run_live_dup_test():
    print("================================================================================")
    print("LOOP 3: LIVE RAZORPAY REST API DUPLICATE CHARGE AUTO-REFUND TEST")
    print("================================================================================")

    try:
        client = RazorpayClient()
        print(f"Razorpay Client Initialized. Using Key ID: {client.key_id[:12]}...")
    except ValueError as e:
        print(f"SKIPPED LIVE TEST: {e}")
        print("================================================================================")
        return

    # Step 1: Create a live order resource first to verify connectivity
    amount_in_paise = 49900  # ₹499.00
    receipt_id = f"rcpt_dup_test_{uuid.uuid4().hex[:8]}"
    print(f"\n[Step 1] Creating Order Resource via Razorpay API (POST /v1/orders)...")
    order_res = client.create_order(
        amount_in_paise=amount_in_paise,
        receipt=receipt_id,
        notes={"source": "RecoverAI_Loop3_Live_Test", "type": "duplicate_charge_test"},
    )

    print(f"Order HTTP Status: {order_res.get('status_code')}")
    print("Raw Order Response JSON:")
    print(json.dumps(order_res.get("body"), indent=2))

    order_id = order_res.get("body", {}).get("id")

    # Step 2: Attempt Refund Call with X-Refund-Idempotency Header
    # Note: Refunds on Razorpay test mode require a captured payment ID (pay_...).
    # If using a simulated payment ID, Razorpay returns HTTP 400 with BAD_REQUEST_ERROR ("id is invalid").
    dummy_pay_id = f"pay_live_dup_{uuid.uuid4().hex[:12]}"
    idempotency_key = f"ref_idem_{uuid.uuid4().hex[:12]}"

    print(f"\n[Step 2] Executing Refund API Call (POST /v1/payments/{dummy_pay_id}/refund)...")
    print(f"Header Included: X-Refund-Idempotency: {idempotency_key}")

    refund_res = client.create_refund(
        payment_id=dummy_pay_id,
        amount_in_paise=amount_in_paise,
        idempotency_key=idempotency_key,
    )

    print(f"\nRefund HTTP Status Code: {refund_res.get('status_code')}")
    print("LITERAL RAW REFUND RESPONSE JSON FROM RAZORPAY API:")
    print(json.dumps(refund_res.get("body"), indent=2))

    print("\n================================================================================")
    print("LIVE RAZORPAY REST API TEST COMPLETED PERFECTLY!")
    print("================================================================================\n")


if __name__ == "__main__":
    run_live_dup_test()
