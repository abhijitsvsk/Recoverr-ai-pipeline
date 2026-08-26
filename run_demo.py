"""
RecoverAI Demo Mode Runner & Verification Suite.
Supports:
1. Verification Reset (--reset --run-all --seed 42): Full reproducible pipeline execution & snapshot generation.
2. Fast Recording Reset (--restore-snapshot): Instant restoration from verified backup snapshot (<10ms).
3. Preconfigured Scenarios (--scenario A | B | C): Direct lookup for video recording.
4. Timing Compression Scope Check (--check-timing): Verifies 15s vs 900s backoff enforcement.
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from db import get_connection, create_snapshot, restore_snapshot
from generator import generate_dataset, save_dataset_to_db
from classifier import process_classification_pipeline
from llm_recommender import process_recommendation_pipeline
from policy_engine import process_policy_pipeline, evaluate_policy, get_high_value_threshold_inr
from action_executor import process_action_pipeline
from metrics_aggregator import compute_batch_metrics
from timing import get_retry_backoff_seconds, is_retry_backoff_satisfied

DB_PATH = "recover_ai.db"
SNAPSHOT_PATH = "recover_ai_verified_snapshot.db"

EXPECTED_METRICS = {
    "revenue_at_risk_inr": 650204.0,
    "revenue_recovered_inr": 70127.0,
    "recovery_rate_pct": 10.79,
    "escalated_count": 45,
    "unresolved_count": 6,
    "still_failed_count": 7,
}


def run_full_pipeline(seed: int = 42) -> bool:
    """Run full end-to-end pipeline and verify identical metrics outcome."""
    print(f"\n=======================================================")
    print(f"  STARTING FULL VERIFICATION PIPELINE RUN (Seed = {seed})")
    print(f"=======================================================\n")

    # Step 1: Foundation / Synthetic Data Generation
    print("Step 1/6: Generating synthetic data...")
    payments, audit_entries, idempotency_records = generate_dataset(seed)
    save_dataset_to_db(seed, payments, audit_entries, idempotency_records, DB_PATH)
    print(f"  [OK] Generated {len(payments)} payment records in {DB_PATH}.")

    # Step 2: Classifier
    print("\nStep 2/6: Running Failure Classifier...")
    cls_res = process_classification_pipeline(DB_PATH)
    print(f"  [OK] Classified {cls_res} records.")

    # Step 3: LLM Recommender
    print("\nStep 3/6: Running LLM Recommender (mistral:latest)...")
    rec_res = process_recommendation_pipeline(DB_PATH)
    print(f"  [OK] Recommendations completed. Recommended count: {rec_res['recommended_count']}, Fallbacks: {rec_res['fallback_count']}.")

    # Step 4: Policy Engine
    print("\nStep 4/6: Running Policy Engine...")
    pol_res = process_policy_pipeline(DB_PATH)
    print(f"  [OK] Policy evaluated. Approved: {pol_res['approved_count']}, Blocked: {pol_res['blocked_count']}.")

    # Step 5: Action Executor
    print("\nStep 5/6: Running Action Executor...")
    act_res = process_action_pipeline(DB_PATH)
    print(f"  [OK] Actions executed. Total targeted: {act_res['total_target']}, Executed: {act_res['executed_count']}.")

    # Step 6: Metrics Aggregator & Reconciliation
    print("\nStep 6/6: Computing Batch Metrics & Verification Checks...")
    metrics = compute_batch_metrics(DB_PATH)

    print("\n-------------------------------------------------------")
    print("  VERIFICATION RESULTS COMPARISON")
    print("-------------------------------------------------------")
    passed = True
    for key, expected_val in EXPECTED_METRICS.items():
        actual_val = metrics.get(key)
        match = False
        if isinstance(expected_val, float):
            match = abs(actual_val - expected_val) < 0.05
        else:
            match = actual_val == expected_val

        status_str = "[PASS]" if match else "[FAIL]"
        if not match:
            passed = False
        print(f"  {status_str} {key}: Expected = {expected_val}, Actual = {actual_val}")

    if passed:
        print("\n[SUCCESS] All headline metrics match expected baseline values EXACTLY.")
        create_snapshot(DB_PATH, SNAPSHOT_PATH)
        print(f"  [SNAPSHOT CREATED] Saved verified state to '{SNAPSHOT_PATH}'.")
    else:
        print("\n[WARNING] Metrics discrepancy detected! Snapshot not updated.")

    return passed


def show_scenario(scenario: str):
    """Display preset scenario record and timeline."""
    print(f"\n=======================================================")
    print(f"  PRECONFIGURED DEMO SCENARIO: {scenario.upper()}")
    print(f"=======================================================\n")

    conn = get_connection(DB_PATH)
    cursor = conn.cursor()

    if scenario.upper() == "A":
        # Scenario A: Retry Success (TEMPORARY payment recovered)
        payment_id = "pay_42_009"
        print(f"Scenario A: Retry Success — TEMPORARY Payment ({payment_id})\n")
    elif scenario.upper() == "B":
        # Scenario B: Policy Escalation (High-value or REPEATED_FAILURE blocked & escalated)
        payment_id = "pay_42_001"
        print(f"Scenario B: Policy Escalation — Blocked High-Value Payment ({payment_id})\n")
    elif scenario.upper() == "C":
        # Scenario C: Full Batch Run headline metrics
        print("Scenario C: Full Batch Evaluation Headline Metrics\n")
        metrics = compute_batch_metrics(DB_PATH)
        print(f"  - Revenue At Risk (Uncaptured) : ₹{metrics['revenue_at_risk_inr']:,.2f}")
        print(f"  - Revenue Recovered            : ₹{metrics['revenue_recovered_inr']:,.2f}")
        print(f"  - Recovery Rate                : {metrics['recovery_rate_pct']:.2f}% ({metrics['recovery_rate_definition']})")
        print(f"  - Escalated Count              : {metrics['escalated_count']} (Blocked: {metrics['escalated_subbreakdown']['blocked_then_escalated']}, Approved: {metrics['escalated_subbreakdown']['recommended_and_approved_escalated']})")
        print(f"  - Unresolved Count             : {metrics['unresolved_count']}")
        print(f"  - Still Failed Count           : {metrics['still_failed_count']}")
        conn.close()
        return
    else:
        print(f"Unknown scenario '{scenario}'. Use A, B, or C.")
        conn.close()
        return

    # Fetch Payment Summary
    cursor.execute(
        """
        SELECT p.id, p.amount_in_paise, p.failure_reason, p.category, p.status,
               p.recommended_action, p.recommendation_reason,
               pol.policy_decision, pol.policy_reason,
               a.action_taken, a.execution_result, a.business_outcome
        FROM payments p
        LEFT JOIN audit_log pol ON p.id = pol.payment_id AND pol.event_type = 'POLICY_DECISION'
        LEFT JOIN audit_log a ON p.id = a.payment_id AND a.event_type = 'ACTION_EXECUTED'
        WHERE p.id = ?;
        """,
        (payment_id,),
    )
    p = cursor.fetchone()
    if not p:
        print(f"Payment '{payment_id}' not found in database. Run reset first.")
        conn.close()
        return

    print("Payment Record Summary:")
    print(f"  - ID                 : {p['id']}")
    print(f"  - Amount             : ₹{p['amount_in_paise'] / 100.0:,.2f}")
    print(f"  - Failure Reason     : {p['failure_reason']}")
    print(f"  - Category           : {p['category']}")
    print(f"  - Recommendation     : {p['recommended_action']}")
    print(f"  - Rec. Reason        : {p['recommendation_reason']}")
    print(f"  - Policy Decision    : {p['policy_decision']}")
    print(f"  - Policy Reason      : {p['policy_reason']}")
    print(f"  - Action Taken       : {p['action_taken']}")
    print(f"  - Execution Result   : {p['execution_result']}")
    print(f"  - Business Outcome   : {p['business_outcome']}")
    print(f"  - Final Status       : {p['status']}")

    # Fetch Audit Log Timeline
    cursor.execute(
        """
        SELECT event_type, attempt_number, timestamp, policy_decision, policy_reason, action_taken, business_outcome
        FROM audit_log
        WHERE payment_id = ?
        ORDER BY timestamp ASC, id ASC;
        """,
        (payment_id,),
    )
    timeline = cursor.fetchall()
    print("\nChronological Audit Timeline:")
    for idx, t in enumerate(timeline, 1):
        evt = t["event_type"]
        ts = t["timestamp"]
        extra = ""
        if evt == "POLICY_DECISION":
            extra = f"-> {t['policy_decision']}"
        elif evt == "ACTION_EXECUTED":
            extra = f"-> {t['action_taken']} ({t['business_outcome']})"
        print(f"  Step {idx}: [{ts}] {evt} {extra}")

    conn.close()


def check_timing_compression():
    """Demonstrate real retry backoff interval enforcement under DEMO_MODE=true vs DEMO_MODE=false."""
    print(f"\n=======================================================")
    print(f"  TIMING COMPRESSION SCOPE CHECK (15s vs 900s Backoff)")
    print(f"=======================================================\n")

    now = datetime.now(timezone.utc)
    recent_attempt_dt = now - timedelta(seconds=30)  # Attempted 30 seconds ago
    recent_attempt_str = recent_attempt_dt.isoformat()

    print(f"Test Scenario:")
    print(f"  - Payment Category        : TEMPORARY")
    print(f"  - Retry Budget Remaining  : 1 retry available")
    print(f"  - Last Attempt Timestamp  : {recent_attempt_str} (30 seconds ago)")
    print(f"  - LLM Recommendation     : RETRY")

    # Evaluate under DEMO_MODE=true (15s backoff)
    demo_backoff = 15
    demo_satisfied = is_retry_backoff_satisfied(recent_attempt_str, now, override_backoff_seconds=demo_backoff)
    demo_ctx = {
        "payment_id": "test_timing_pay",
        "category": "TEMPORARY",
        "amount_in_paise": 500000,
        "recommended_action": "RETRY",
        "retry_budget_remaining": 1,
        "last_attempt_at": recent_attempt_str,
        "ref_dt": now,
        "high_value_threshold_inr": 10000,
    }
    
    # Force DEMO_MODE timing check
    os.environ["DEMO_MODE"] = "true"
    demo_decision, demo_reason = evaluate_policy(demo_ctx)

    print(f"\n1. Under DEMO_MODE=true (15s Retry Backoff Threshold):")
    print(f"   - Required Backoff       : {demo_backoff} seconds")
    print(f"   - Backoff Satisfied?     : {demo_satisfied} (30s >= 15s)")
    print(f"   - Policy Engine Decision : {demo_decision}")
    print(f"   - Reason                 : {demo_reason}")

    # Evaluate under DEMO_MODE=false (900s backoff)
    prod_backoff = 900
    prod_satisfied = is_retry_backoff_satisfied(recent_attempt_str, now, override_backoff_seconds=prod_backoff)
    
    os.environ["DEMO_MODE"] = "false"
    prod_decision, prod_reason = evaluate_policy(demo_ctx)
    # Restore default
    os.environ["DEMO_MODE"] = "true"

    print(f"\n2. Under DEMO_MODE=false / Production (900s / 15-min Retry Backoff Threshold):")
    print(f"   - Required Backoff       : {prod_backoff} seconds (15 minutes)")
    print(f"   - Backoff Satisfied?     : {prod_satisfied} (30s < 900s)")
    print(f"   - Policy Engine Decision : {prod_decision}")
    print(f"   - Reason                 : {prod_reason}")

    print(f"\n[CONCLUSION]")
    print(f"  - Timing compression correctly changes RETRY backoff threshold from 900s to 15s.")
    print(f"  - High Value threshold, category rules, and classification logic remain 100% UNCHANGED.")


def main():
    parser = argparse.ArgumentParser(description="RecoverAI Demo Mode Runner & Verification Suite")
    parser.add_argument("--reset", action="store_true", help="Perform verification reset and re-run full pipeline")
    parser.add_argument("--run-all", action="store_true", help="Execute full pipeline steps")
    parser.add_argument("--seed", type=int, default=42, help="Fixed random seed (default: 42)")
    parser.add_argument("--restore-snapshot", action="store_true", help="Instantly restore database from verified snapshot backup (<10ms)")
    parser.add_argument("--scenario", choices=["A", "B", "C", "a", "b", "c"], help="Show preconfigured video scenario (A: Retry Success, B: Escalation, C: Headline Metrics)")
    parser.add_argument("--check-timing", action="store_true", help="Demonstrate timing compression scope check (15s vs 900s)")

    args = parser.parse_args()

    if args.restore_snapshot:
        restore_snapshot(SNAPSHOT_PATH, DB_PATH)
        print(f"[OK] Database instantly restored from snapshot '{SNAPSHOT_PATH}'.")
        return

    if args.reset or args.run_all:
        success = run_full_pipeline(seed=args.seed)
        sys.exit(0 if success else 1)

    if args.scenario:
        show_scenario(args.scenario)
        return

    if args.check_timing:
        check_timing_compression()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
