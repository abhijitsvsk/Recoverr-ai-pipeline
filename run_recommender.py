"""
Runner & Verification Suite for RecoverAI LLM Recommender.
Runs recommendation pipeline across classified payments and audits context sensitivity and action validity.
"""

import argparse
import json
import sqlite3
import sys
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db import init_db, get_connection
from generator import generate_dataset, save_dataset_to_db
from classifier import process_classification_pipeline
from llm_recommender import (
    process_recommendation_pipeline,
    ALLOWED_ACTIONS,
    PROMPT_TEMPLATE,
    compute_time_since_last_attempt,
    get_high_value_threshold_inr,
)


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI LLM Recommender Runner")
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Integer seed for dataset generation (default: 42)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def run_and_validate_recommender(db_path: str) -> Dict[str, Any]:
    """Execute recommendation pipeline and validate actions, prompt, context, and audit log."""
    pipeline_res = process_recommendation_pipeline(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, amount_in_paise, failure_reason, ground_truth_category, category, 
               status, attempt_count, last_attempt_at, recommended_action, recommendation_reason 
        FROM payments 
        ORDER BY id;
        """
    )
    payments = cursor.fetchall()

    # 1. Action Validity Check & Breakdown Table
    action_breakdown = {}
    invalid_actions = []
    empty_reasons = []

    high_value_thresh_paise = get_high_value_threshold_inr() * 100

    for p in payments:
        cat = p["category"]
        action = p["recommended_action"]
        reason = p["recommendation_reason"]

        if action not in ALLOWED_ACTIONS:
            invalid_actions.append((p["id"], action))

        if not reason or len(reason.strip()) == 0:
            empty_reasons.append(p["id"])

        if cat not in action_breakdown:
            action_breakdown[cat] = {}
        action_breakdown[cat][action] = action_breakdown[cat].get(action, 0) + 1

    assert len(invalid_actions) == 0, f"Found invalid recommended actions: {invalid_actions}"
    assert len(empty_reasons) == 0, f"Found empty recommendation reasons for IDs: {empty_reasons}"

    # 2. Fetch 10 sample payments with full context for inspection
    sample_records = []
    for p in payments[:10]:
        attempt_count = p["attempt_count"]
        retries_used = max(0, attempt_count - 1)
        retry_budget_remaining = max(0, 2 - retries_used)
        amount_in_paise = p["amount_in_paise"]

        sample_records.append(
            {
                "payment_id": p["id"],
                "category": p["category"],
                "attempt_count": attempt_count,
                "amount_in_paise": amount_in_paise,
                "amount_in_inr": amount_in_paise / 100.0,
                "retry_budget_remaining": retry_budget_remaining,
                "time_since_last_attempt": compute_time_since_last_attempt(p["last_attempt_at"]),
                "exceeds_high_value_threshold": amount_in_paise > high_value_thresh_paise,
                "recommended_action": p["recommended_action"],
                "recommendation_reason": p["recommendation_reason"],
            }
        )

    # 3. Verify RECOMMENDED audit log entries exist for every record
    cursor.execute(
        """
        SELECT COUNT(*) as count 
        FROM audit_log 
        WHERE event_type = 'RECOMMENDED';
        """
    )
    audit_rec_count = cursor.fetchone()["count"]

    conn.close()

    return {
        "total_payments": len(payments),
        "recommended_count": pipeline_res["recommended_count"],
        "fallback_count": pipeline_res["fallback_count"],
        "fallback_records": pipeline_res["fallback_records"],
        "action_breakdown": action_breakdown,
        "sample_records": sample_records,
        "audit_rec_count": audit_rec_count,
    }


def main():
    args = parse_args()

    # 1. Setup DB and run classifier first to ensure status = CLASSIFIED
    init_db(args.db_path)
    payments, audit_entries, idempotency_records = generate_dataset(args.seed)
    save_dataset_to_db(args.seed, payments, audit_entries, idempotency_records, args.db_path)
    process_classification_pipeline(args.db_path)

    print("\n" + "=" * 80)
    print("EXACT PROMPT TEMPLATE SENT TO LLM")
    print("=" * 80)
    sample_context_prompt = PROMPT_TEMPLATE.format(
        payment_id="pay_sample_001",
        category="TEMPORARY",
        attempt_count=1,
        amount_in_inr=499.00,
        amount_in_paise=49900,
        time_since_last_attempt="2 hours ago",
        retry_budget_remaining=2,
        exceeds_high_value_threshold=False,
        high_value_threshold_inr=get_high_value_threshold_inr(),
    )
    print(sample_context_prompt)

    print("\n" + "=" * 80)
    print(f"RUNNING LLM RECOMMENDER PIPELINE (Dataset Seed: {args.seed})")
    print("=" * 80)

    res = run_and_validate_recommender(args.db_path)

    print(f"\nTotal Records Processed   : {res['recommended_count']} / {res['total_payments']}")
    print(f"LLM API Fallback Count    : {res['fallback_count']}")

    if res["fallback_records"]:
        print("\nFALLBACK RECORDS LIST (Payment IDs and Errors):")
        print(json.dumps(res["fallback_records"], indent=2))
    else:
        print("0 Fallbacks! 100% of payment recommendations were generated by real LLM API model calls.")

    print("\n" + "=" * 80)
    print("RECOMMENDED ACTION BREAKDOWN BY CATEGORY")
    print("=" * 80)
    for cat, actions in res["action_breakdown"].items():
        actions_str = ", ".join([f"{act}: {cnt}" for act, cnt in actions.items()])
        print(f"  - {cat:<18} -> {actions_str}")

    print("\n" + "=" * 80)
    print("10 SAMPLE PAYMENTS WITH CONTEXT & REASONED RECOMMENDATIONS")
    print("=" * 80)
    print(json.dumps(res["sample_records"], indent=2))

    print("\n" + "=" * 80)
    print("AUDIT LOG VERIFICATION")
    print("=" * 80)
    print(f"Total RECOMMENDED audit log rows created: {res['audit_rec_count']}")
    assert res["audit_rec_count"] == res["total_payments"], "Audit log count mismatch!"
    print("Verified: Every payment has a corresponding 'RECOMMENDED' audit_log entry.")

    print("\nLLM Recommender run and validation complete!")


if __name__ == "__main__":
    main()
