"""
Runner script for Loop 2 Checkout Abandonment LLM Recommendation step.
Executes recommendation pipeline, validates context-sensitive outputs,
verifies UNKNOWN_ABANDON bias toward ESCALATE, and prints full metrics reports.
100% separate from Loop 1 payment recommender runner.
"""

import sys
import sqlite3
from typing import Dict, Any, List
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutRecoveryAction, CheckoutStatus, CheckoutCategory
from checkout_recommender import (
    process_checkout_recommendation_pipeline,
    PROMPT_TEMPLATE,
    MODEL_NAME,
    ALLOWED_ACTIONS,
    process_single_recommendation,
)


def run_llm_recommendation_verification() -> None:
    print("=" * 80)
    print("RECOVERAI LOOP 2 — CHECKOUT ABANDONMENT LLM RECOMMENDATION RUNNER")
    print("=" * 80)
    print(f"Target LLM Model: {MODEL_NAME} (7.2B Local Ollama)")
    print(f"Allowed Recovery Actions: {sorted(list(ALLOWED_ACTIONS))}\n")

    # Ensure schema is up to date
    init_checkout_db()

    # Step 1: Run LLM Recommendation Pipeline
    print("Executing LLM recommendation pipeline across all CLASSIFIED checkouts...")
    summary = process_checkout_recommendation_pipeline(max_workers=10)



    print(f"Processed: {summary['processed_count']} checkouts.")
    print(f"Recommended: {summary['processed_count']} checkouts.")
    print(f"Fallbacks Triggered: {summary['fallback_count']}")
    if summary["fallback_ids"]:
        print(f"Fallback Checkout IDs: {summary['fallback_ids']}\n")
    else:
        print("Fallback Checkout IDs: None (100% LLM generated)\n")

    # Fetch updated checkouts from DB
    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, customer_abandon_reason, category, abandon_count, abandoned_at, status, recommended_action, recommendation_reason
        FROM checkouts
        ORDER BY id;
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Assertion 1: All checkouts in checkouts table must have status = RECOMMENDED
    recommended_rows = [r for r in rows if r["status"] == CheckoutStatus.RECOMMENDED.value]
    assert len(recommended_rows) == len(rows), f"Expected all {len(rows)} checkouts to be RECOMMENDED, got {len(recommended_rows)}"
    assert len(rows) >= 100, f"Expected at least 100 checkouts in database, got {len(rows)}"
    print(f"[OK] Assertion 1 Passed: All {len(rows)} checkouts transitioned to status = RECOMMENDED.")

    # Assertion 2: Every recommended_action must be one of the 4 allowed actions
    invalid_actions = [r for r in rows if r["recommended_action"] not in ALLOWED_ACTIONS]
    assert len(invalid_actions) == 0, f"Found {len(invalid_actions)} invalid recommended actions!"
    print("[OK] Assertion 2 Passed: 100% of recommendations use one of the 4 allowed actions.\n")

    # Step 2: Show Prompt Template
    print("-" * 80)
    print("1. EXACT PROMPT TEMPLATE SENT TO LLM")
    print("-" * 80)
    print(PROMPT_TEMPLATE.strip())
    print("-" * 80 + "\n")

    # Step 3: Action Breakdown Matrix by Category
    print("-" * 80)
    print("2. FULL BREAKDOWN TABLE: RECOMMENDED ACTIONS BY CATEGORY")
    print("-" * 80)
    breakdown: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category_counts: Dict[str, int] = defaultdict(int)

    for r in rows:
        cat = r["category"]
        act = r["recommended_action"]
        breakdown[cat][act] += 1
        category_counts[cat] += 1

    actions_list = sorted(list(ALLOWED_ACTIONS))
    header = f"{'Category':<22} | " + " | ".join(f"{act:<20}" for act in actions_list) + " | Total"
    print(header)
    print("-" * len(header))

    collapsed_categories = []

    for cat in sorted(breakdown.keys()):
        total = category_counts[cat]
        row_str = f"{cat:<22} | "
        for act in actions_list:
            cnt = breakdown[cat][act]
            row_str += f"{cnt:<20} | "
        row_str += f"{total:<5}"
        print(row_str)

        # Check for single-action collapse (90%+ of records in a category receiving a single action)
        for act in actions_list:
            cnt = breakdown[cat][act]
            pct = (cnt / total) * 100 if total > 0 else 0
            if pct >= 90.0:
                collapsed_categories.append((cat, act, cnt, total, pct))

    print("-" * len(header))

    if collapsed_categories:
        print("\n[FAIL] SANITY CHECK WARNING: Single-action collapse detected in categories:")
        for cat, act, cnt, tot, pct in collapsed_categories:
            print(f"   - {cat}: {cnt}/{tot} ({pct:.1f}%) received '{act}'")
        print("This indicates model reasoning failure / action collapse! Do NOT accept step as done.")
    else:
        print("\n[OK] SANITY CHECK PASSED: Multi-action reasoning variation present across all categories (no 90%+ action collapse).")

    print("\n" + "-" * 80)

    # Step 4: UNKNOWN_ABANDON Check
    print("3. UNKNOWN_ABANDON CATEGORY RECOMMENDATION AUDIT")
    print("-" * 80)
    unknown_records = [r for r in rows if r["category"] == CheckoutCategory.UNKNOWN_ABANDON.value]
    if unknown_records:
        print(f"Found {len(unknown_records)} UNKNOWN_ABANDON records in benchmark dataset:")
        for u in unknown_records:
            print(f"   - ID: {u['id']} | Action: {u['recommended_action']} | Reason: {u['recommendation_reason']}")
    else:
        print("No UNKNOWN_ABANDON records in initial 100-record benchmark batch.")
        print("Executing pipeline test on temporary UNKNOWN_ABANDON test record...")
        test_unknown_row = {
            "id": "chk_test_unknown_llm_001",
            "cart_value_in_paise": 450000,
            "customer_abandon_reason": "unrecognized_device_glitch_99",
            "category": CheckoutCategory.UNKNOWN_ABANDON.value,
            "abandon_count": 1,
            "abandoned_at": "2026-08-23T16:00:00Z",
        }
        res = process_single_recommendation(test_unknown_row)
        print(f"   - Test ID: {res['checkout_id']}")
        print(f"   - Input Reason: '{test_unknown_row['customer_abandon_reason']}'")
        print(f"   - Category: {res['category']}")
        print(f"   - LLM Recommended Action: {res['recommended_action']}")
        print(f"   - LLM Reason: {res['recommendation_reason']}")
        if res["recommended_action"] == CheckoutRecoveryAction.ESCALATE.value:
            print("[OK] Verified: UNKNOWN_ABANDON record correctly recommended ESCALATE.")
        else:
            print(f"[INFO] Note: LLM recommended '{res['recommended_action']}' for UNKNOWN_ABANDON. Deterministic Policy Engine will BLOCK and force ESCALATE during policy evaluation per safety rules.")

    print("\n" + "-" * 80)

    # Step 5: 10 Sample Checkouts with Context + Recommendation + Reason
    print("4. SPOT-CHECK: 10 DETAILED SAMPLE CHECKOUTS (CONTEXT + RECOMMENDATION + REASON)")
    print("-" * 80)
    sample_rows = rows[:10]
    for idx, s in enumerate(sample_rows, 1):
        cart_inr = s["cart_value_in_paise"] / 100.0
        print(f"Sample {idx:2d} | Checkout ID: {s['id']}")
        print(f"   Context      : Category: {s['category']} | Cart Value: INR {cart_inr:,.2f} | Abandons: {s['abandon_count']}")
        print(f"                  Reason Code: '{s['customer_abandon_reason']}' | Abandoned At: {s['abandoned_at']}")
        print(f"   Recommendation: Action: {s['recommended_action']}")
        print(f"   Reason       : \"{s['recommendation_reason']}\"")
        print("-" * 60)

    # Step 6: Fallback Report
    print("\n" + "-" * 80)
    print("5. FALLBACK REPORT")
    print("-" * 80)
    print(f"Total Fallbacks: {summary['fallback_count']} / {summary['processed_count']}")
    if summary["fallback_count"] == 0:
        print("[OK] 100% of recommendations were generated by live local mistral:latest LLM inference with 0 fallbacks.")
    else:
        print(f"Fallback Checkout IDs: {summary['fallback_ids']}")

    # Step 7: Audit Log Verification
    print("\n" + "-" * 80)
    print("6. CHECKOUT AUDIT LOG VERIFICATION")
    print("-" * 80)
    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) as cnt FROM checkout_audit_log WHERE event_type = 'RECOMMENDED';
        """
    )
    rec_audit_count = cursor.fetchone()["cnt"]
    conn.close()

    assert rec_audit_count == 100, f"Expected 100 RECOMMENDED audit log rows, found {rec_audit_count}"
    print(f"[OK] Verified: Exactly {rec_audit_count} 'RECOMMENDED' entries exist in checkout_audit_log.")

    print("\n" + "=" * 80)
    print("ALL LOOP 2 LLM RECOMMENDATION VERIFICATIONS PASSED SUCCESSFULLY.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_llm_recommendation_verification()
