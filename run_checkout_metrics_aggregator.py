"""
Runner script for Loop 2 Checkout Abandonment Batch Metrics Aggregation.
Simulates deterministic conversion outcomes, computes batch headline metrics,
verifies reconciliation invariants, and prints full category breakdown table.
100% separate from Loop 1 metrics aggregator runner.
"""

import sys
import sqlite3
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_metrics_aggregator import (
    simulate_checkout_conversions,
    compute_checkout_batch_metrics,
)


def run_checkout_metrics_verification() -> None:
    print("=" * 80)
    print("RECOVERAI LOOP 2 — CHECKOUT ABANDONMENT BATCH METRICS AGGREGATOR RUNNER")
    print("=" * 80)

    # Ensure schema is initialized
    init_checkout_db()

    # Step 1: Run Conversion Simulation Step
    print("Executing deterministic conversion simulation step...")
    conv_res = simulate_checkout_conversions()

    print(f"Modeled Conversion Rates Applied:")
    print(f"  - SEND_CART_REMINDER : ~25% rate -> {conv_res['reminder_converted']} / {conv_res['reminder_total']} converted")
    print(f"  - SEND_DISCOUNT_NUDGE: ~40% rate -> {conv_res['nudge_converted']} / {conv_res['nudge_total']} converted\n")

    # Step 2: Compute Batch Metrics
    metrics = compute_checkout_batch_metrics()

    at_risk_inr = metrics["carts_at_risk_paise"] / 100.0
    recovered_inr = metrics["carts_recovered_paise"] / 100.0

    print("-" * 80)
    print("1. HEADLINE METRICS SUMMARY")
    print("-" * 80)
    print(f"Carts At Risk (Uncaptured Revenue) : INR {at_risk_inr:,.2f} ({metrics['carts_at_risk_paise']:,} paise)")
    print(f"Carts Recovered                   : INR {recovered_inr:,.2f} ({metrics['carts_recovered_paise']:,} paise)")
    print(f"Recovery Rate                     : {metrics['recovery_rate']:.2f}% [{metrics['recovery_rate_definition']}]")
    print(f"Total Escalated Checkouts          : {metrics['escalated_count']}")
    print(f"  - Direct Policy-Approved ESCALATE: {metrics['direct_approved_escalated_cnt']} (15 HIGH_VALUE + 12 REPEAT_ABANDONER)")
    print(f"  - Policy-Blocked-Then-Escalated  : {metrics['policy_blocked_escalated_cnt']} (20 STALE_ABANDON + 8 REPEAT_ABANDONER)")
    print(f"Total Unresolved Checkouts (STOP)  : {metrics['unresolved_count']}")
    print(f"  - Note: {metrics['unresolved_explanation']}\n")

    # Step 3: Full Category Breakdown Table
    print("-" * 80)
    print("2. CATEGORY BREAKDOWN TABLE")
    print("-" * 80)

    header = f"{'Category':<22} | {'Count':<6} | {'Carts At Risk (INR)':<20} | {'Carts Recovered (INR)':<22} | {'Recovery Rate':<14}"
    print(header)
    print("-" * len(header))

    cat_metrics = metrics["category_metrics"]
    for cat in sorted(cat_metrics.keys()):
        m = cat_metrics[cat]
        risk_inr = m["at_risk_paise"] / 100.0
        rec_inr = m["recovered_paise"] / 100.0
        rate_str = f"{m['recovery_rate']:.2f}%"
        print(f"{cat:<22} | {m['count']:<6} | INR {risk_inr:<16,.2f} | INR {rec_inr:<18,.2f} | {rate_str:<14}")

    print("-" * len(header))
    print(f"{'Total':<22} | {metrics['total_checkouts']:<6} | INR {at_risk_inr:<16,.2f} | INR {recovered_inr:<18,.2f} | {metrics['recovery_rate']:.2f}%")
    print("-" * len(header) + "\n")

    # Step 4: Manual Spot Check of Carts At Risk
    print("-" * 80)
    print("3. MANUAL SPOT CHECK & RECONCILIATION INVARIANTS")
    print("-" * 80)

    conn = get_checkout_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, cart_value_in_paise FROM checkouts ORDER BY id LIMIT 5;")
    spot_rows = cursor.fetchall()
    conn.close()

    spot_sum_paise = sum(r["cart_value_in_paise"] for r in spot_rows)
    print("Spot-checking first 5 records cart values:")
    for r in spot_rows:
        print(f"  - {r['id']}: {r['cart_value_in_paise']:,} paise (INR {r['cart_value_in_paise']/100:,.2f})")
    print(f"  Spot Check Sum (First 5): {spot_sum_paise:,} paise (INR {spot_sum_paise/100:,.2f})")

    # Invariant 1: Sum Reconciliation (Converted + Unconverted + Escalated + Unresolved == 100)
    assert metrics["sum_reconciliation"] == 100, f"Sum reconciliation failed: got {metrics['sum_reconciliation']}"
    print(f"[OK] Sum Reconciliation Passed: {metrics['converted_count']} Converted + {metrics['unconverted_count']} Unconverted + {metrics['escalated_count']} Escalated + {metrics['unresolved_count']} Unresolved = {metrics['sum_reconciliation']} / 100.")

    # Invariant 2: Zero Overlaps (No checkout is both converted AND escalated)
    assert metrics["overlap_count"] == 0, f"Overlap violation: found {metrics['overlap_count']} checkouts both converted and escalated!"
    print(f"[OK] Overlap Verification Passed: Exactly {metrics['overlap_count']} overlaps detected between converted and escalated checkouts.\n")

    print("=" * 80)
    print("ALL LOOP 2 BATCH METRICS AGGREGATION VERIFICATIONS PASSED SUCCESSFULLY.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_checkout_metrics_verification()
