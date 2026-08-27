"""
Action Executor for Loop 3: Duplicate Charge Detection & Auto-Refund.
The ONLY component allowed to execute refunds or call external APIs.
Idempotent execution with append-only audit logging.
"""

import os
import json
import uuid
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from dup_models import DupCategory, DupAction, DupStatus
from dup_db import get_dup_connection
from razorpay_client import RazorpayClient


def execute_dup_refund(
    charge_id: str,
    amount_in_paise: int,
    is_live_api: bool = False,
) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
    """
    Execute auto-refund action.
    If is_live_api=True or charge_id starts with 'pay_live_', calls real Razorpay Refund REST API.
    """
    if is_live_api or charge_id.startswith("pay_live_") or charge_id.startswith("pay_rzp_"):
        client = RazorpayClient()
        idempotency_key = f"ref_idem_{uuid.uuid4().hex[:12]}"
        
        # Step A: Ensure target payment is captured first
        pay_info = client.get_payment(charge_id)
        if pay_info.get("status") == "authorized":
            client.capture_payment(charge_id, amount_in_paise)
        
        # Step B: Execute Refund with X-Refund-Idempotency header
        res = client.create_refund(
            payment_id=charge_id,
            amount_in_paise=amount_in_paise,
            idempotency_key=idempotency_key,
        )
        status_code = res.get("status_code", 500)
        is_ok = status_code in (200, 201)

        exec_res = f"razorpay_refund_http_{status_code}"
        bus_out = "refund_processed" if is_ok else "refund_failed"
        res_status = DupStatus.SUCCEEDED.value if is_ok else DupStatus.FAILED_EXECUTION.value

        live_log = {
            "execution_mode": "REAL_RAZORPAY_REFUND_API",
            "endpoint": f"/v1/payments/{charge_id}/refund",
            "idempotency_key": idempotency_key,
            "http_status_code": status_code,
            "response_body": res.get("body"),
        }
        return exec_res, bus_out, res_status, live_log

    # Deterministic simulation for synthetic batch evaluation
    exec_res = "simulated_refund_processed"
    bus_out = "refund_issued"
    res_status = DupStatus.SUCCEEDED.value
    sim_log = {"mode": "SIMULATED_DUP_REFUND", "charge_id": charge_id, "amount_in_paise": amount_in_paise}
    return exec_res, bus_out, res_status, sim_log


def process_dup_action_pipeline(db_path: str = "duplicate_charge.db") -> Dict[str, Any]:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, amount_in_paise, category, recommended_action, policy_decision, policy_reason, status
        FROM duplicate_charges
        WHERE status IN ('APPROVED', 'BLOCKED');
    """)
    target_rows = cursor.fetchall()

    executed_count = 0
    skipped_duplicate_count = 0
    action_breakdown = {}
    now_str = datetime.now(timezone.utc).isoformat()

    for r in target_rows:
        cid = r["id"]
        amount = r["amount_in_paise"]
        cat = r["category"]
        pol_dec = r["policy_decision"]
        pol_reason = r["policy_reason"]
        rec_act = r["recommended_action"]
        current_status = r["status"]

        event_id = f"evt_dup_act_{cid}"

        # 1. Idempotency Check
        cursor.execute("SELECT processed_at FROM dup_idempotency WHERE event_id = ?;", (event_id,))
        if cursor.fetchone():
            skipped_duplicate_count += 1
            continue

        # 2. Write Idempotency Entry Before Execution
        cursor.execute(
            "INSERT INTO dup_idempotency (event_id, charge_id, processed_at) VALUES (?, ?, ?);",
            (event_id, cid, now_str),
        )

        # 3. Determine Final Action
        is_live_api = cid.startswith("pay_live_") or cid.startswith("pay_rzp_") or cid.startswith("chg_live_")
        
        if current_status == DupStatus.BLOCKED.value:
            if cat == DupCategory.UNRELATED.value:
                action_taken = DupAction.NO_ACTION.value
                exec_res = "no_action_required"
                bus_out = "legitimate_purchase_confirmed"
                res_status = DupStatus.NO_ACTION_TAKEN.value
            else:
                action_taken = DupAction.HOLD_FOR_REVIEW.value
                exec_res = "blocked_routed_to_review"
                bus_out = "hold_for_manual_review"
                res_status = DupStatus.ESCALATED.value
        else:
            action_taken = rec_act
            if action_taken == DupAction.AUTO_REFUND.value:
                exec_res, bus_out, res_status, _ = execute_dup_refund(cid, amount, is_live_api=is_live_api)
            elif action_taken == DupAction.HOLD_FOR_REVIEW.value:
                exec_res = "queued_for_ops_review"
                bus_out = "hold_for_manual_review"
                res_status = DupStatus.ESCALATED.value
            elif action_taken == DupAction.ESCALATE_AS_FRAUD.value:
                exec_res = "fraud_escalation_logged"
                bus_out = "escalated_to_security"
                res_status = DupStatus.ESCALATED.value
            elif action_taken == DupAction.NO_ACTION.value:
                exec_res = "no_action_taken"
                bus_out = "legitimate_purchase_confirmed"
                res_status = DupStatus.NO_ACTION_TAKEN.value
            else:
                exec_res = "unknown_action"
                bus_out = "unresolved"
                res_status = DupStatus.ESCALATED.value

        executed_count += 1
        key = (action_taken, res_status, exec_res, bus_out)
        action_breakdown[key] = action_breakdown.get(key, 0) + 1

        # 4. Write Audit Log Row
        audit_id = f"aud_dup_act_{cid}"
        cursor.execute(
            """
            INSERT INTO dup_audit_log (
                id, event_id, event_type, charge_id, timestamp,
                amount_in_paise, category, recommended_action, policy_decision,
                policy_reason, action_taken, execution_result, business_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                audit_id, event_id, "ACTION_EXECUTED", cid, now_str,
                amount, cat, rec_act, pol_dec, pol_reason,
                action_taken, exec_res, bus_out,
            ),
        )

        # 5. Update Status
        cursor.execute(
            """
            UPDATE duplicate_charges
            SET action_taken = ?, execution_result = ?, business_outcome = ?, status = ?, updated_at = ?
            WHERE id = ?;
            """,
            (action_taken, exec_res, bus_out, res_status, now_str, cid),
        )

    conn.commit()
    conn.close()

    return {
        "executed_count": executed_count,
        "skipped_duplicate_count": skipped_duplicate_count,
        "action_breakdown": action_breakdown,
    }
