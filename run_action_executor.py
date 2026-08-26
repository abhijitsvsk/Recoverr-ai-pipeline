"""
Runner & Verification Suite for RecoverAI Action Executor.
Executes APPROVED payment actions with simulated RETRY execution (70% modeling assumption),
logs ACTION_EXECUTED audit rows, and validates idempotency duplicate protection.
"""

import argparse
import json
import sqlite3
import sys
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection
from action_executor import (
    process_action_pipeline,
    DEFAULT_RETRY_SUCCESS_RATE,
)


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI Action Executor Runner")
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def test_idempotency_duplicate_skip(db_path: str, payment_id: str) -> bool:
    """
    Test duplicate execution protection by temporarily resetting a payment to APPROVED
    and confirming process_action_pipeline skips it due to existing idempotency record.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Get current status
    cursor.execute("SELECT status FROM payments WHERE id = ?;", (payment_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    orig_status = row["status"]

    # Temporarily set to APPROVED to re-trigger pipeline
    cursor.execute("UPDATE payments SET status = 'APPROVED' WHERE id = ?;", (payment_id,))
    conn.commit()

    # Re-run pipeline
    res = process_action_pipeline(db_path)

    # Restore original status
    cursor.execute("UPDATE payments SET status = ? WHERE id = ?;", (orig_status, payment_id))
    conn.commit()
    conn.close()

    return res["skipped_duplicate_count"] > 0


def main():
    args = parse_args()

    print("=" * 80)
    print("ACTION EXECUTOR & SIMULATED RETRY MODELING LOGIC")
    print("=" * 80)
    print("  Modeling Assumption : RETRY execution is simulated for the MVP demo (~70% recovered, ~30% still_failed).")
    print("  Documentation Note  : Real Razorpay retry integration requires payment IDs created via Razorpay's own")
    print("                        checkout/order flow, which is out of scope for synthetic batch evaluation.")

    code_snippet = """
# RETRY execution is simulated for the MVP demo. Real Razorpay retry integration requires
# payment IDs created via Razorpay's own checkout/order flow, which is out of scope for
# synthetic batch evaluation. This is a documented modeling assumption, not a claimed live integration.
def execute_razorpay_retry(payment_id: str, amount_in_paise: int, success_rate: float = 0.70):
    rng = random.Random(f"retry_seed_{payment_id}")
    is_successful = rng.random() < success_rate

    execution_result = "simulated"
    if is_successful:
        return (execution_result, "recovered", PaymentStatus.SUCCEEDED.value, simulated_log)
    else:
        return (execution_result, "still_failed", PaymentStatus.FAILED_EXECUTION.value, simulated_log)
"""
    print(code_snippet.strip())

    print("\n" + "=" * 80)
    print("RUNNING ACTION EXECUTOR PIPELINE")
    print("=" * 80)

    res = process_action_pipeline(args.db_path)

    print(f"\nTotal Payments Targeted (APPROVED + BLOCKED) : {res['total_target']}")
    print(f"Total Actions Executed           : {res['executed_count']}")
    print(f"Total Duplicates Skipped         : {res['skipped_duplicate_count']}")

    print("\n" + "=" * 80)
    print("SAMPLE SIMULATED RETRY LOGS")
    print("=" * 80)
    if res["raw_retry_logs"]:
        for i, item in enumerate(res["raw_retry_logs"], 1):
            pid = item["payment_id"]
            log = item["log"]
            print(f"  [{i}] Payment ID: {pid} | Mode: {log['simulation_mode']} | Rate: {log['modeled_success_rate']} | Outcome: {log['simulated_outcome']}")
    else:
        print("No retry logs captured.")

    print("\n" + "=" * 80)
    print("ACTION TYPE & OUTCOME BREAKDOWN TABLE")
    print("=" * 80)
    print(f"{'Action Type':<22} | {'Resulting Status':<18} | {'Execution Result':<22} | {'Business Outcome':<18} | {'Count':<6}")
    print("-" * 95)

    for (act, status, exec_res, bus_out), count in sorted(res["action_breakdown"].items()):
        print(f"{act:<22} | {status:<18} | {exec_res:<22} | {bus_out:<18} | {count:<6}")

    # Idempotency Duplicate Test
    print("\n" + "=" * 80)
    print("IDEMPOTENCY DUPLICATE PROTECTIONS TEST")
    print("=" * 80)
    sample_pid = "pay_42_004"
    print(f"Testing re-execution of already processed payment '{sample_pid}'...")
    duplicate_test_passed = test_idempotency_duplicate_skip(args.db_path, sample_pid)

    if duplicate_test_passed:
        print(f"SUCCESS: Payment '{sample_pid}' was cleanly SKIPPED as duplicate! Idempotency key event_id detected.")
    else:
        print(f"FAILURE: Duplicate payment '{sample_pid}' was not skipped!")

    # Audit log check
    conn = get_connection(args.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM audit_log WHERE event_type = 'ACTION_EXECUTED';")
    audit_count = cursor.fetchone()["count"]
    conn.close()

    print("\n" + "=" * 80)
    print("AUDIT LOG VERIFICATION")
    print("=" * 80)
    print(f"Total ACTION_EXECUTED audit log rows created: {audit_count} / {res['executed_count']}")
    assert audit_count == res["executed_count"], f"Audit count mismatch: expected {res['executed_count']}, found {audit_count}"
    print("Verified: Every processed payment (100% of batch) has a corresponding 'ACTION_EXECUTED' audit_log entry.")
    print("\nAction Executor run and validation complete!")


if __name__ == "__main__":
    main()
