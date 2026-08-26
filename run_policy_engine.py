"""
Runner & Verification Suite for RecoverAI Policy Engine.
Executes policy engine across RECOMMENDED payments and audits policy decisions.
"""

import argparse
import json
import sqlite3
import sys
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db import get_connection
from models import PaymentStatus, Category, RecoveryAction
from policy_engine import (
    process_policy_pipeline,
    evaluate_policy,
    get_allowed_actions,
    get_high_value_threshold_inr,
)


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI Policy Engine Runner")
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def run_and_validate_policy_engine(db_path: str) -> Dict[str, Any]:
    """Execute policy engine pipeline and validate decisions, allowed sets, and audit logs."""
    pipeline_res = process_policy_pipeline(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Audit log verification
    cursor.execute(
        """
        SELECT COUNT(*) as count FROM audit_log WHERE event_type = 'POLICY_DECISION';
        """
    )
    audit_count = cursor.fetchone()["count"]

    # 2. Check for zero invalid approvals (Invariant check)
    cursor.execute(
        """
        SELECT p.id, p.category, p.amount_in_paise, p.attempt_count, p.recommended_action
        FROM payments p
        WHERE p.status = 'APPROVED';
        """
    )
    approved_rows = cursor.fetchall()
    invalid_approvals = []

    high_value_thresh_inr = get_high_value_threshold_inr()
    high_value_thresh_paise = high_value_thresh_inr * 100

    for r in approved_rows:
        cat = r["category"]
        amt_paise = r["amount_in_paise"]
        attempts = r["attempt_count"]
        rec_action = r["recommended_action"]
        retries_used = max(0, attempts - 1)
        retry_budget_remaining = max(0, 2 - retries_used)

        allowed = get_allowed_actions(cat, amt_paise, retry_budget_remaining, high_value_thresh_paise)
        if rec_action not in allowed:
            invalid_approvals.append((r["id"], cat, amt_paise, rec_action, allowed))

    conn.close()

    assert (
        len(invalid_approvals) == 0
    ), f"INVARIANT VIOLATION: Found approved payments with disallowed actions: {invalid_approvals}"
    assert (
        audit_count == pipeline_res["processed_count"]
    ), f"Audit count mismatch: expected {pipeline_res['processed_count']}, found {audit_count}"

    pipeline_res["audit_count"] = audit_count
    pipeline_res["invalid_approvals_count"] = len(invalid_approvals)
    return pipeline_res


def main():
    args = parse_args()

    print("=" * 80)
    print("DETERMINISTIC POLICY ENGINE CODE LOGIC")
    print("=" * 80)
    code_snippet = """
def evaluate_policy(context: Dict[str, Any]) -> Tuple[str, str]:
    category = context["category"]
    amount_in_paise = context["amount_in_paise"]
    recommended_action = context["recommended_action"]
    retry_budget_remaining = context["retry_budget_remaining"]
    high_value_thresh_paise = context["high_value_threshold_inr"] * 100

    is_high_value = amount_in_paise > high_value_thresh_paise

    # 1. HARD OVERRIDE CHECK (Rule 1)
    if is_high_value and category in (Category.REPEATED_FAILURE.value, Category.UNKNOWN.value):
        if recommended_action != RecoveryAction.STOP.value:
            return ("BLOCKED", f"BLOCKED: Hard override — amount exceeds high-value threshold in '{category}' category. Mandatory action is STOP.")
        else:
            return ("APPROVED", f"APPROVED: Hard override — STOP action mandatory for high-value {category} payment.")

    # 2. CATEGORY / CONTEXT ALLOWED ACTION CHECK (Rule 2)
    allowed_actions = get_allowed_actions(category, amount_in_paise, retry_budget_remaining, high_value_thresh_paise)

    if recommended_action in allowed_actions:
        return ("APPROVED", f"APPROVED: '{recommended_action}' is in allowed actions {allowed_actions}.")
    else:
        return ("BLOCKED", f"BLOCKED: '{recommended_action}' is not in allowed actions {allowed_actions}.")
"""
    print(code_snippet.strip())
    print("\n" + "=" * 80)
    print("RUNNING POLICY ENGINE PIPELINE")
    print("=" * 80)

    res = run_and_validate_policy_engine(args.db_path)

    print(f"\nTotal Payments Evaluated : {res['processed_count']} / 100")
    print(f"Total APPROVED           : {res['approved_count']}")
    print(f"Total BLOCKED            : {res['blocked_count']}")

    print("\n" + "=" * 80)
    print("APPROVED / BLOCKED BREAKDOWN BY CATEGORY")
    print("=" * 80)
    categories = ["TEMPORARY", "PERMANENT", "REPEATED_FAILURE", "UNKNOWN"]
    for cat in categories:
        app = res["approved_by_category"].get(cat, 0)
        blk = res["blocked_by_category"].get(cat, 0)
        tot = app + blk
        print(f"  - {cat:<18} -> APPROVED: {app:<3} | BLOCKED: {blk:<3} | TOTAL: {tot}")

    print("\n" + "=" * 80)
    print(f"ALL BLOCKED RECORDS ({len(res['blocked_records'])}) WITH POLICY REASONS")
    print("=" * 80)
    for b in res["blocked_records"]:
        print(
            f"  Payment ID: {b['payment_id']} | Category: {b['category']:<16} | Amount: INR {b['amount_in_inr']:>9,.2f} | RecAction: {b['recommended_action']:<18}"
        )
        print(f"    └─ Policy Reason: {b['policy_reason']}")

    print("\n" + "=" * 80)
    print("INVARIANT & AUDIT LOG VERIFICATION")
    print("=" * 80)
    print(f"Total POLICY_DECISION audit log rows created : {res['audit_count']}")
    print(f"Total Invalid Approvals (Invariant Violations): {res['invalid_approvals_count']}")
    print("Verified: Zero payments incorrectly APPROVED with disallowed actions!")
    print("Verified: Every evaluated payment has a corresponding 'POLICY_DECISION' audit_log entry.")
    print("\nPolicy Engine run and validation complete!")


if __name__ == "__main__":
    main()
