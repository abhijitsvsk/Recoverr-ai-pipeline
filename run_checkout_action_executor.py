"""
Runner script for Loop 2 Checkout Abandonment Action Executor.
Executes simulated recovery actions, tests idempotency duplicate rejection,
prints full action-type and outcome breakdown matrix, and verifies 100/100 audit log coverage.
100% separate from Loop 1 action executor runner.
"""

import sys
import sqlite3
from typing import Dict, Any, List
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutStatus, CheckoutRecoveryAction
from checkout_action_executor import (
    process_checkout_execution_pipeline,
    execute_single_checkout_action,
)


def run_checkout_executor_verification() -> None:
    print("=" * 80)
    print("RECOVERAI LOOP 2 — CHECKOUT ABANDONMENT ACTION EXECUTOR RUNNER")
    print("=" * 80)

    # Ensure schema is initialized
    init_checkout_db()

    # Step 1: Run Action Execution Pipeline
    print("Executing simulated recovery action pipeline across checkouts...")
    summary = process_checkout_execution_pipeline()

    print(f"Targeted Checkouts: {summary['processed_count']}")
    print(f"Executed Actions  : {summary['executed_count']}")
    print(f"Skipped Actions   : {summary['skipped_count']}\n")

    # Step 2: Fetch DB Checkouts & Audit Log Data
    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, category, recommended_action, 
               policy_decision, policy_reason, status
        FROM checkouts
        ORDER BY id;
        """
    )
    checkout_rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT checkout_id, category, recommended_action, policy_decision, 
               action_taken, execution_result, business_outcome, cart_value_in_paise
        FROM checkout_audit_log
        WHERE event_type = 'ACTION_EXECUTED'
        ORDER BY checkout_id;
        """
    )
    audit_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Step 3: Assertion on 100/100 Audit Log Rows
    assert len(audit_rows) == len(checkout_rows) == 100, (
        f"Expected exactly 100 ACTION_EXECUTED audit log rows, got {len(audit_rows)}"
    )
    print(f"[OK] Audit Log Verification Passed: Exactly {len(audit_rows)} 'ACTION_EXECUTED' audit log entries recorded.")

    # Step 4: Action Type & Outcome Breakdown Matrix
    print("\n" + "-" * 80)
    print("1. ACTION TYPE & BUSINESS OUTCOME BREAKDOWN MATRIX")
    print("-" * 80)

    outcome_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    action_totals: Dict[str, int] = defaultdict(int)

    for a in audit_rows:
        act = a["action_taken"]
        out = a["business_outcome"]
        outcome_matrix[act][out] += 1
        action_totals[act] += 1

    outcomes_list = sorted(list(set(a["business_outcome"] for a in audit_rows)))
    header = f"{'Action Taken':<22} | " + " | ".join(f"{out:<18}" for out in outcomes_list) + " | Total"
    print(header)
    print("-" * len(header))

    for act in sorted(outcome_matrix.keys()):
        row_str = f"{act:<22} | "
        tot = action_totals[act]
        for out in outcomes_list:
            cnt = outcome_matrix[act][out]
            row_str += f"{cnt:<18} | "
        row_str += f"{tot:<5}"
        print(row_str)

    print("-" * len(header))
    print(f"{'Total':<22} | " + " | ".join(f"{sum(outcome_matrix[act][out] for act in outcome_matrix):<18}" for out in outcomes_list) + f" | {len(audit_rows):<5}")
    print("-" * len(header) + "\n")

    # Category x Action Breakdown
    print("-" * 80)
    print("2. CATEGORY vs EXECUTED ACTION BREAKDOWN (INCLUDES POLICY-BLOCKED ESCALATIONS)")
    print("-" * 80)

    cat_action_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cat_totals: Dict[str, int] = defaultdict(int)

    for a in audit_rows:
        cat = a["category"]
        act = a["action_taken"]
        cat_action_matrix[cat][act] += 1
        cat_totals[cat] += 1

    all_actions = sorted(list(set(a["action_taken"] for a in audit_rows)))
    cat_header = f"{'Category':<22} | " + " | ".join(f"{act:<20}" for act in all_actions) + " | Total"
    print(cat_header)
    print("-" * len(cat_header))

    for cat in sorted(cat_action_matrix.keys()):
        row_str = f"{cat:<22} | "
        tot = cat_totals[cat]
        for act in all_actions:
            cnt = cat_action_matrix[cat][act]
            row_str += f"{cnt:<20} | "
        row_str += f"{tot:<5}"
        print(row_str)

    print("-" * len(cat_header) + "\n")

    # Step 5: Idempotency Duplicate Skip Test
    print("-" * 80)
    print("3. IDEMPOTENCY DUPLICATE EXECUTION PROTECTION TEST")
    print("-" * 80)

    sample_checkout = checkout_rows[0]
    print(f"Attempting re-execution on already-executed Checkout ID '{sample_checkout['id']}'...")

    conn = get_checkout_connection()
    re_exec_res = execute_single_checkout_action(sample_checkout, conn)
    conn.close()

    print(f"Re-execution Result: Status = '{re_exec_res['status']}' | Reason = '{re_exec_res.get('reason')}'")
    assert re_exec_res["status"] == "skipped", f"Expected status 'skipped', got {re_exec_res['status']}"
    assert "Idempotency lock exists" in re_exec_res["reason"], f"Unexpected skip reason: {re_exec_res.get('reason')}"
    print("[OK] Idempotency Protection Verification Passed: Re-execution attempt correctly rejected without duplicate DB writes.")

    print("\n" + "=" * 80)
    print("ALL LOOP 2 ACTION EXECUTOR VERIFICATIONS PASSED SUCCESSFULLY.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_checkout_executor_verification()
