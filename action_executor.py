"""
Action Executor for RecoverAI Payment Recovery Agent.
The ONLY component allowed to call external APIs (AGENTS.md rule 6).
Executes actions for APPROVED payments:
- RETRY -> Simulated execution with deterministic outcome (~70% recovered, ~30% still_failed)
- SEND_RECOVERY_LINK -> Simulated URL generation
- ESCALATE -> DB status write (ESCALATED)
- STOP -> DB status write (STOPPED)

Enforces idempotency (AGENTS.md rule 8) and writes immutable ACTION_EXECUTED audit log rows.
"""

import os
import uuid
import json
import random
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from db import get_connection
from models import PaymentStatus, Category, RecoveryAction
from razorpay_client import RazorpayClient

# RETRY execution is simulated for the MVP synthetic batch demo. Real Razorpay API integration
# is invoked exclusively for live-test payment IDs (e.g. starting with 'pay_live_') or payments
# with real Razorpay order IDs.
DEFAULT_RETRY_SUCCESS_RATE = 0.70  # Model assumption for synthetic batch evaluation


def execute_razorpay_retry(
    payment_id: str,
    amount_in_paise: int,
    success_rate: float = DEFAULT_RETRY_SUCCESS_RATE,
    is_live_api: bool = False,
) -> Tuple[str, str, str, Dict[str, Any]]:
    """
    Execute payment retry action.
    If is_live_api=True or payment_id starts with 'pay_live_', calls real Razorpay REST API.
    Otherwise, executes deterministic simulation for synthetic batch evaluation.
    """
    if is_live_api or payment_id.startswith("pay_live_") or payment_id.startswith("pay_rzp_"):
        client = RazorpayClient()
        # Call Razorpay Orders API for real test order / retry execution
        api_res = client.create_order(
            amount_in_paise=amount_in_paise,
            receipt=f"rcpt_retry_{payment_id}",
            notes={"action": "RETRY", "payment_id": payment_id},
        )
        status_code = api_res.get("status_code", 500)
        is_successful = status_code in (200, 201)

        execution_result = f"razorpay_api_http_{status_code}"
        if is_successful:
            business_outcome = "razorpay_order_created"
            resulting_status = PaymentStatus.EXECUTING.value
        else:
            business_outcome = "still_failed"
            resulting_status = PaymentStatus.FAILED_EXECUTION.value

        live_log = {
            "execution_mode": "REAL_RAZORPAY_API_CALL",
            "endpoint": "/v1/orders",
            "payment_id": payment_id,
            "http_status_code": status_code,
            "response_body": api_res.get("body"),
            "raw_body": api_res.get("raw_body"),
        }
        return (execution_result, business_outcome, resulting_status, live_log)

    # Deterministic simulation seeded by payment_id for synthetic batch evaluation (pay_42_XXX)
    rng = random.Random(f"retry_seed_{payment_id}")
    is_successful = rng.random() < success_rate

    simulated_log = {
        "simulation_mode": "SIMULATED_RETRY_MVP",
        "payment_id": payment_id,
        "modeled_success_rate": f"{int(success_rate * 100)}%",
        "simulated_outcome": "captured" if is_successful else "failed",
        "documentation_note": (
            "RETRY execution is simulated for the MVP synthetic batch demo. Real Razorpay retry "
            "integration requires payment IDs created via Razorpay's own checkout/order flow, "
            "which is out of scope for synthetic batch evaluation. This is a documented modeling "
            "assumption, not a claimed live integration."
        ),
    }

    execution_result = "simulated"
    if is_successful:
        business_outcome = "recovered"
        resulting_status = PaymentStatus.SUCCEEDED.value
    else:
        business_outcome = "still_failed"
        resulting_status = PaymentStatus.FAILED_EXECUTION.value

    return (execution_result, business_outcome, resulting_status, simulated_log)


def execute_send_recovery_link(
    payment_id: str, amount_in_paise: int = 100000, is_live_api: bool = False
) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
    """Generate recovery link URL via real Razorpay Payment Links API or simulation."""
    if is_live_api or payment_id.startswith("pay_live_") or payment_id.startswith("pay_rzp_"):
        client = RazorpayClient()
        api_res = client.create_payment_link(
            amount_in_paise=amount_in_paise,
            description=f"Payment Recovery Link for {payment_id}",
            notes={"payment_id": payment_id},
        )
        status_code = api_res.get("status_code", 500)
        body = api_res.get("body", {})

        short_url = body.get("short_url", f"https://rzp.io/i/test_{payment_id}")
        live_log = {
            "execution_mode": "REAL_RAZORPAY_PAYMENT_LINK_API",
            "endpoint": "/v1/payment_links",
            "payment_id": payment_id,
            "http_status_code": status_code,
            "short_url": short_url,
            "response_body": body,
            "raw_body": api_res.get("raw_body"),
        }
        return (f"razorpay_link_http_{status_code}", "link_sent", PaymentStatus.SUCCEEDED.value, live_log)

    link_token = str(uuid.uuid4())
    recovery_url = f"https://recover.razorpay.com/pay/{link_token}"
    return ("link_generated", "link_sent", PaymentStatus.SUCCEEDED.value, None)


def _load_env_file(env_path: str = ".env") -> None:
    """Load key-value pairs from .env file into os.environ if present."""
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1].strip()
                    os.environ[k.strip()] = val


def post_to_slack_webhook(
    webhook_url: str,
    payment_id: str,
    category: str,
    amount_in_paise: int,
    policy_reason: str,
    timestamp: str,
) -> Tuple[bool, str]:
    """
    POST escalation notification to Slack Webhook using Python standard library (urllib.request).
    Returns (success_boolean, raw_http_response_or_error_string).
    Slack failures are safely caught and never raise an exception.
    """
    import urllib.request
    import urllib.error

    amount_inr = amount_in_paise / 100.0
    payload = {
        "text": f"🚨 *Payment Escalated for Human Ops Review*\n"
                f"• *Payment ID*: `{payment_id}`\n"
                f"• *Category*: `{category}`\n"
                f"• *Amount*: `₹{amount_inr:,.2f}`\n"
                f"• *Reason*: {policy_reason}\n"
                f"• *Timestamp*: `{timestamp}`",
        "payment_id": payment_id,
        "category": category,
        "amount_in_paise": amount_in_paise,
        "amount_inr": amount_inr,
        "policy_reason": policy_reason,
        "timestamp": timestamp,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_body = response.read().decode("utf-8")
            return (True, res_body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return (False, f"HTTP_{e.code}: {err_body}")
    except Exception as e:
        return (False, f"ERROR: {str(e)}")


def execute_escalate(
    payment_id: str,
    category: str = "UNKNOWN",
    amount_in_paise: int = 0,
    policy_reason: str = "Escalated for human ops review",
) -> Tuple[str, str, str]:
    """
    Escalate payment to human ops review (DB status update + optional Slack notification).
    If SLACK_WEBHOOK_URL is set in environment or .env, posts a real message via urllib.request.
    Slack posting failure never blocks or crashes escalation (AGENTS.md rule 4 & 6).
    """
    _load_env_file()
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    execution_result = "logged"
    if slack_url:
        now_str = datetime.now(timezone.utc).isoformat()
        ok, res_text = post_to_slack_webhook(
            slack_url, payment_id, category, amount_in_paise, policy_reason, now_str
        )
        if ok:
            execution_result = f"logged_slack_sent: {res_text.strip()}"
        else:
            execution_result = f"logged_slack_failed: {res_text.strip()}"

    return (execution_result, "escalated", PaymentStatus.ESCALATED.value)


def execute_stop(payment_id: str) -> Tuple[str, str, str]:
    """Stop recovery processing for payment (DB status update)."""
    return ("no_action", "unresolved", PaymentStatus.STOPPED.value)


def process_action_pipeline(db_path: str = "recover_ai.db") -> Dict[str, Any]:
    """
    Process all payments at status = 'APPROVED'.
    Enforces idempotency, executes corresponding action, writes audit log, and updates status.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, amount_in_paise, category, attempt_count, recommended_action, recommendation_reason, status 
        FROM payments 
        WHERE status IN ('APPROVED', 'BLOCKED');
        """
    )
    target_payments = cursor.fetchall()

    executed_count = 0
    skipped_duplicate_count = 0
    action_breakdown = {}
    raw_retry_logs = []
    now_str = datetime.now(timezone.utc).isoformat()

    for row in target_payments:
        payment_id = row["id"]
        amount_in_paise = row["amount_in_paise"]
        category = row["category"]
        attempt_count = row["attempt_count"]
        rec_action = row["recommended_action"]
        current_status = row["status"]

        event_id = f"evt_act_{payment_id}"

        # 1. IDEMPOTENCY CHECK (AGENTS.md rule 8)
        cursor.execute("SELECT processed_at FROM idempotency WHERE event_id = ?;", (event_id,))
        idem_row = cursor.fetchone()
        if idem_row:
            skipped_duplicate_count += 1
            print(f"  [IDEMPOTENCY SKIP] Payment {payment_id} - event {event_id} already executed at {idem_row['processed_at']}.")
            continue

        # 2. WRITE IDEMPOTENCY RECORD BEFORE ACTING
        cursor.execute(
            "INSERT INTO idempotency (event_id, payment_id, processed_at) VALUES (?, ?, ?);",
            (event_id, payment_id, now_str),
        )

        # 3. EXECUTE ACTION
        raw_log = None
        if current_status == PaymentStatus.BLOCKED.value:
            # BLOCKED recommendations route to ESCALATED per State Machine Rule 4
            action_taken = RecoveryAction.ESCALATE.value
            pol_dec = "BLOCKED"
            pol_reason = "BLOCKED recommendation routed to ESCALATED for human ops review"
            exec_res, bus_out, res_status = execute_escalate(
                payment_id, category=category, amount_in_paise=amount_in_paise, policy_reason=pol_reason
            )
        else:
            action_taken = rec_action
            pol_dec = "APPROVED"
            pol_reason = "Action executed by Policy Engine approval"

            is_live_api = payment_id.startswith("pay_live_") or payment_id.startswith("pay_rzp_")
            if action_taken == RecoveryAction.RETRY.value:
                exec_res, bus_out, res_status, raw_log = execute_razorpay_retry(
                    payment_id, amount_in_paise, is_live_api=is_live_api
                )
                if len(raw_retry_logs) < 5 and raw_log is not None:
                    raw_retry_logs.append({"payment_id": payment_id, "log": raw_log})

            elif action_taken == RecoveryAction.SEND_RECOVERY_LINK.value:
                exec_res, bus_out, res_status, raw_log = execute_send_recovery_link(
                    payment_id, amount_in_paise, is_live_api=is_live_api
                )

            elif action_taken == RecoveryAction.ESCALATE.value:
                exec_res, bus_out, res_status = execute_escalate(
                    payment_id, category=category, amount_in_paise=amount_in_paise, policy_reason=pol_reason
                )

            elif action_taken == RecoveryAction.STOP.value:
                exec_res, bus_out, res_status = execute_stop(payment_id)

            else:
                exec_res, bus_out, res_status = ("unknown_action", "unresolved", PaymentStatus.STOPPED.value)

        executed_count += 1

        # Track action type and resulting status breakdown
        key = (action_taken, res_status, exec_res, bus_out)
        action_breakdown[key] = action_breakdown.get(key, 0) + 1

        # 4. WRITE AUDIT LOG ENTRY (ACTION_EXECUTED)
        audit_id = f"aud_act_{payment_id}"
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
                "ACTION_EXECUTED",
                payment_id,
                attempt_count,
                now_str,
                category,
                rec_action,
                pol_dec,
                pol_reason,
                action_taken,
                exec_res,
                bus_out,
                amount_in_paise,
            ),
        )

        # 5. UPDATE PAYMENT STATUS
        cursor.execute(
            """
            UPDATE payments
            SET status = ?, updated_at = ?
            WHERE id = ?;
            """,
            (res_status, now_str, payment_id),
        )

    conn.commit()
    conn.close()

    return {
        "total_target": len(target_payments),
        "executed_count": executed_count,
        "skipped_duplicate_count": skipped_duplicate_count,
        "action_breakdown": action_breakdown,
        "raw_retry_logs": raw_retry_logs,
    }
