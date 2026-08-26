"""
Runner script for Loop 2 Checkout Abandonment Policy Engine.
Evaluates deterministic policy rules across all 100 RECOMMENDED checkouts,
asserts exact invariant rules, prints detailed metrics & blocked records tables,
and verifies 100% audit log coverage.
100% separate from Loop 1 policy engine runner.
"""

import sys
import sqlite3
from typing import Dict, Any, List
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutCategory, CheckoutStatus, CheckoutRecoveryAction
from checkout_policy_engine import (
    process_checkout_policy_pipeline,
    evaluate_checkout_policy,
    ALLOWED_ACTIONS_BY_CATEGORY,
)


def run_checkout_policy_verification() -> None:
    print("=" * 80)
    print("RECOVERAI LOOP 2 — CHECKOUT ABANDONMENT POLICY ENGINE RUNNER")
    print("=" * 80)

    # Ensure schema is up to date
    init_checkout_db()

    # Step 1: Query initial state before processing
    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM checkouts")
    rec_before_count = cursor.fetchone()["cnt"]
    conn.close()

    assert rec_before_count >= 100, f"Expected at least 100 checkouts, found {rec_before_count}"
    print(f"Targeting {rec_before_count} RECOMMENDED checkouts for policy evaluation...\n")

    # Step 2: Execute Policy Pipeline
    summary = process_checkout_policy_pipeline()

    print(f"Processed: {summary['processed_count']} checkouts.")
    print(f"APPROVED : {summary['approved_count']} checkouts.")
    print(f"BLOCKED  : {summary['blocked_count']} checkouts.\n")

    # Step 3: Fetch post-pipeline checkouts and audit log data
    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, customer_abandon_reason, category, 
               recommended_action, policy_decision, policy_reason, status
        FROM checkouts
        ORDER BY id;
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT checkout_id, category, recommended_action, policy_decision, policy_reason, cart_value_in_paise
        FROM checkout_audit_log
        WHERE event_type = 'POLICY_DECISION'
        ORDER BY checkout_id;
        """
    )
    audit_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Assert 100 audit log rows exist
    assert len(audit_rows) == len(rows), f"Expected {len(rows)} POLICY_DECISION audit rows, got {len(audit_rows)}"
    print(f"[OK] Audit Log Verification Passed: Exactly {len(audit_rows)} 'POLICY_DECISION' audit rows recorded.")

    # Step 4: Category Breakdown Matrix (APPROVED vs BLOCKED)
    print("\n" + "-" * 80)
    print("1. APPROVED vs BLOCKED DECISION BREAKDOWN BY CATEGORY")
    print("-" * 80)

    breakdown: Dict[str, Dict[str, int]] = defaultdict(lambda: {"APPROVED": 0, "BLOCKED": 0})
    category_totals: Dict[str, int] = defaultdict(int)

    for r in rows:
        cat = r["category"]
        dec = r["policy_decision"]
        breakdown[cat][dec] += 1
        category_totals[cat] += 1

    header = f"{'Category':<22} | {'APPROVED':<10} | {'BLOCKED':<10} | Total"
    print(header)
    print("-" * len(header))

    for cat in sorted(breakdown.keys()):
        app_cnt = breakdown[cat]["APPROVED"]
        blk_cnt = breakdown[cat]["BLOCKED"]
        tot_cnt = category_totals[cat]
        print(f"{cat:<22} | {app_cnt:<10} | {blk_cnt:<10} | {tot_cnt:<5}")

    print("-" * len(header))
    print(f"{'Total':<22} | {summary['approved_count']:<10} | {summary['blocked_count']:<10} | {summary['processed_count']:<5}")
    print("-" * len(header) + "\n")

    # Step 5: Specific Verification Assertions (User-Requested Rules)

    # Specific Verification 1: All STALE_ABANDON records must be BLOCKED
    stale_rows = [r for r in rows if r["category"] == CheckoutCategory.STALE_ABANDON.value]
    stale_approved = [r for r in stale_rows if r["policy_decision"] == "APPROVED"]
    stale_blocked = [r for r in stale_rows if r["policy_decision"] == "BLOCKED"]
    assert len(stale_approved) == 0, f"BUG: Found {len(stale_approved)} STALE_ABANDON records incorrectly APPROVED!"
    assert len(stale_blocked) == len(stale_rows), f"Expected all {len(stale_rows)} STALE_ABANDON to be BLOCKED, got {len(stale_blocked)}"
    print(f"[OK] Assertion 1 Passed: 100% of STALE_ABANDON records ({len(stale_blocked)}/{len(stale_rows)}) are BLOCKED.")

    # Specific Verification 2: REPEAT_ABANDONER - All SEND_DISCOUNT_NUDGE are BLOCKED, all ESCALATE are APPROVED
    repeat_rows = [r for r in rows if r["category"] == CheckoutCategory.REPEAT_ABANDONER.value]
    repeat_blocked = [r for r in repeat_rows if r["policy_decision"] == "BLOCKED"]
    repeat_approved = [r for r in repeat_rows if r["policy_decision"] == "APPROVED"]
    for r in repeat_blocked:
        assert r["recommended_action"] == CheckoutRecoveryAction.SEND_DISCOUNT_NUDGE.value, f"Expected BLOCKED REPEAT_ABANDONER to have action SEND_DISCOUNT_NUDGE, got {r['recommended_action']}"
    for r in repeat_approved:
        assert r["recommended_action"] == CheckoutRecoveryAction.ESCALATE.value, f"Expected APPROVED REPEAT_ABANDONER to have action ESCALATE, got {r['recommended_action']}"
    print(f"[OK] Assertion 2 Passed: REPEAT_ABANDONER correctly evaluated ({len(repeat_approved)} APPROVED with ESCALATE, {len(repeat_blocked)} BLOCKED with SEND_DISCOUNT_NUDGE).")

    # Specific Verification 3: All 15 HIGH_VALUE_ABANDON are APPROVED (recommended ESCALATE)
    hv_rows = [r for r in rows if r["category"] == CheckoutCategory.HIGH_VALUE_ABANDON.value]
    hv_approved = [r for r in hv_rows if r["policy_decision"] == "APPROVED"]
    assert len(hv_approved) == len(hv_rows) == 15, f"Expected 15 HIGH_VALUE_ABANDON APPROVED, got {len(hv_approved)}"
    print(f"[OK] Assertion 3 Passed: 100% of HIGH_VALUE_ABANDON records ({len(hv_approved)}/15) are APPROVED.")

    # Specific Verification 4: Zero checkouts APPROVED with action outside category's allowed set
    disallowed_approvals = []
    for r in rows:
        if r["policy_decision"] == "APPROVED":
            cat = r["category"]
            act = r["recommended_action"]
            allowed_set = ALLOWED_ACTIONS_BY_CATEGORY.get(cat, set())
            if act not in allowed_set:
                disallowed_approvals.append(r)

    assert len(disallowed_approvals) == 0, f"INVARIANT VIOLATION: Found {len(disallowed_approvals)} APPROVED checkouts with disallowed actions!"
    print(f"[OK] Invariant Verification Passed: Zero checkouts were APPROVED with an action outside their allowed category set.\n")

    # Step 6: Detailed List of ALL BLOCKED Records with Policy Reason
    print("-" * 80)
    print(f"2. DETAILED LIST OF ALL {summary['blocked_count']} BLOCKED RECORDS & POLICY REASONS")
    print("-" * 80)

    blocked_records = [r for r in rows if r["policy_decision"] == "BLOCKED"]
    for idx, b in enumerate(blocked_records, 1):
        cart_inr = b["cart_value_in_paise"] / 100.0
        print(f"Blocked {idx:2d} | Checkout ID: {b['id']}")
        print(f"           Category          : {b['category']}")
        print(f"           Recommended Action: {b['recommended_action']}")
        print(f"           Cart Value        : INR {cart_inr:,.2f}")
        print(f"           Policy Reason     : {b['policy_reason']}")
        print(f"           Final Status      : {b['status']}")
        print("-" * 60)

    print("\n" + "=" * 80)
    print("ALL LOOP 2 POLICY ENGINE VERIFICATIONS PASSED SUCCESSFULLY.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_checkout_policy_verification()
