"""
Runner & Verification Suite for RecoverAI Batch Metrics Aggregator.
Calculates headline metrics, recovery rates, category breakdowns, and reconciliation checks.
"""

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from metrics_aggregator import (
    compute_batch_metrics,
    simulate_link_conversions,
    DEFAULT_LINK_CONVERSION_RATE,
)


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI Batch Metrics Aggregator Runner")
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 80)
    print("RECOVERY LINK CONVERSION SIMULATION CODE LOGIC (~30% Modeled Rate)")
    print("=" * 80)
    sim_code = """
# Recovery link conversion is simulated for the MVP demo (~30% modeled conversion rate).
# Real customer conversion requires user interaction on the recovery link, which is out of
# scope for synthetic batch evaluation. This is a documented modeling assumption, not a real result.
def simulate_link_conversions(db_path: str = "recover_ai.db", conversion_rate: float = 0.30) -> Dict[str, bool]:
    # ...
    for pid in link_sent_payments:
        rng = random.Random(f"link_conversion_{pid}")
        conversions[pid] = rng.random() < conversion_rate
    return conversions
"""
    print(sim_code.strip())

    print("\n" + "=" * 80)
    print("FULL BATCH METRICS CALCULATION CODE LOGIC")
    print("=" * 80)
    metrics_code = """
def compute_batch_metrics(db_path: str = "recover_ai.db"):
    revenue_at_risk_paise = sum(amount_in_paise for ALL 100 payments)
    revenue_recovered_paise = sum(amount_in_paise for RETRY 'recovered' + LINK 'recovery_confirmed')
    recovery_rate_pct = (revenue_recovered_paise / revenue_at_risk_paise) * 100.0
    escalated_count = count(status == 'ESCALATED') # blocked_escalated + recommended_escalated
    unresolved_count = count(status == 'STOPPED')
"""
    print(metrics_code.strip())

    metrics = compute_batch_metrics(args.db_path)

    print("\n" + "=" * 80)
    print("LINK CONVERSION SIMULATION RESULT")
    print("=" * 80)
    print(f"Total SEND_RECOVERY_LINK Payments : {metrics['link_sent_total']}")
    print(f"Simulated Converted Links (30% rate): {metrics['link_converted_count']} / {metrics['link_sent_total']} (~{metrics['link_converted_count']/metrics['link_sent_total']*100:.1f}%)")
    print(f"Unconverted Recovery Links         : {metrics['link_unconverted_count']}")

    print("\n" + "=" * 80)
    print("FINAL HEADLINE BATCH METRICS")
    print("=" * 80)
    print(f"  Revenue At Risk (Uncaptured Revenue) : INR {metrics['revenue_at_risk_inr']:>12,.2f} ({metrics['revenue_at_risk_paise']} paise)")
    print(f"  Revenue Recovered                    : INR {metrics['revenue_recovered_inr']:>12,.2f} ({metrics['revenue_recovered_paise']} paise)")
    print(f"  Overall Batch Recovery Rate          : {metrics['recovery_rate_pct']:>6.2f}%")
    print(f"    └─ Rate Definition String          : {metrics['recovery_rate_definition']}")
    print(f"  Total Escalated Payments             : {metrics['escalated_count']:>6}")
    print(f"    ├─ Policy-Blocked & Escalated      : {metrics['escalated_subbreakdown']['blocked_then_escalated']:>6}")
    print(f"    └─ Policy-Approved & Escalated     : {metrics['escalated_subbreakdown']['recommended_and_approved_escalated']:>6}")
    print(f"  Total Unresolved Payments (STOPPED)  : {metrics['unresolved_count']:>6}")
    print(f"  Total Still-Failed Payments (RETRY)  : {metrics['still_failed_count']:>6}")

    print("\n" + "=" * 80)
    print("CATEGORY BREAKDOWN TABLE")
    print("=" * 80)
    print(f"{'Category':<18} | {'Count':<6} | {'Revenue At Risk (INR)':<22} | {'Revenue Recovered (INR)':<24} | {'Recovery Rate (%)':<18}")
    print("-" * 98)

    for cat, d in metrics["category_breakdown"].items():
        print(
            f"{cat:<18} | {d['count']:<6} | INR {d['at_risk_inr']:>17,.2f} | INR {d['recovered_inr']:>19,.2f} | {d['recovery_rate_pct']:>16.2f}%"
        )

    print("\n" + "=" * 80)
    print("RECONCILIATION & INTEGRITY CHECKS")
    print("=" * 80)
    rec = metrics["reconciliation"]
    print(f"Total Batch Payments Counted           : {rec['sum_check_total']} / 100")
    print(f"Reconciliation Sum-to-100 Check        : {'PASSED (Exact 100)' if rec['is_sum_exact_100'] else 'FAILED'}")
    print(f"Overlap Check (Recovered & Escalated)  : {rec['overlap_count']} overlaps")
    print(f"Zero-Overlap Invariant Check           : {'PASSED (Zero Overlaps)' if rec['is_zero_overlap'] else 'FAILED'}")

    assert rec["is_sum_exact_100"], "RECONCILIATION ERROR: Payment counts do not sum to 100!"
    assert rec["is_zero_overlap"], "INVARIANT ERROR: Overlaps found between recovered and escalated/stopped payments!"

    print("\nBatch Metrics Aggregation and Validation complete!")


if __name__ == "__main__":
    main()
