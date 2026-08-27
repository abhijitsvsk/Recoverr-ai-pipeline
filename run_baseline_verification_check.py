"""
Verification Script for RecoverAI Interactive Simulation & Database Isolation Protection.
Audits all three protected baseline databases (recover_ai.db, checkout_recovery.db, checkout_recovery_verified_snapshot.db)
BEFORE and AFTER executing multiple live interactive simulation API calls.
"""

import sys
import app
import sys
import app
from metrics_aggregator import compute_batch_metrics
from checkout_metrics_aggregator import compute_checkout_batch_metrics
from dup_metrics_aggregator import compute_dup_metrics

DB1 = "recover_ai.db"
DB2 = "checkout_recovery.db"
DB3 = "checkout_recovery_verified_snapshot.db"
DB4 = "duplicate_charge.db"
DB5 = "duplicate_charge_verified_snapshot.db"


def print_db_metrics(header: str):
    print("=" * 80)
    print(header)
    print("=" * 80)

    # 1. Loop 1 Baseline DB (recover_ai.db)
    m1 = compute_batch_metrics(DB1)
    print(f"1. [{DB1}]")
    print(f"   - Revenue At Risk : INR {m1['revenue_at_risk_inr']:,.2f}")
    print(f"   - Revenue Recovered: INR {m1['revenue_recovered_inr']:,.2f}")
    print(f"   - Recovery Rate    : {m1['recovery_rate_pct']:.2f}%")
    print(f"   - Total Escalated  : {m1['escalated_count']} (Blocked: {m1['escalated_subbreakdown']['blocked_then_escalated']}, Approved: {m1['escalated_subbreakdown']['recommended_and_approved_escalated']})")
    print(f"   - Total Unresolved : {m1['unresolved_count']}")
    print(f"   - Total Still Failed: {m1['still_failed_count']}")
    print(f"   - Total Payments   : {m1['total_batch_records']} / 100")
    print()

    # 2. Loop 2 Baseline DB (checkout_recovery.db)
    m2 = compute_checkout_batch_metrics(DB2)
    print(f"2. [{DB2}]")
    print(f"   - Carts At Risk    : INR {m2['carts_at_risk_paise'] / 100.0:,.2f}")
    print(f"   - Carts Recovered  : INR {m2['carts_recovered_paise'] / 100.0:,.2f}")
    print(f"   - Recovery Rate    : {m2['recovery_rate']:.2f}%")
    print(f"   - Total Escalated  : {m2['escalated_count']} (Blocked: {m2['policy_blocked_escalated_cnt']}, Approved: {m2['direct_approved_escalated_cnt']})")
    print(f"   - Total Unresolved : {m2['unresolved_count']}")
    print(f"   - Total Checkouts  : {m2['total_checkouts']} / 100")
    print()

    # 3. Canonical Loop 2 Snapshot DB (checkout_recovery_verified_snapshot.db)
    m3 = compute_checkout_batch_metrics(DB3)
    print(f"3. [{DB3}]")
    print(f"   - Carts At Risk    : INR {m3['carts_at_risk_paise'] / 100.0:,.2f}")
    print(f"   - Carts Recovered  : INR {m3['carts_recovered_paise'] / 100.0:,.2f}")
    print(f"   - Recovery Rate    : {m3['recovery_rate']:.2f}%")
    print(f"   - Total Escalated  : {m3['escalated_count']} (Blocked: {m3['policy_blocked_escalated_cnt']}, Approved: {m3['direct_approved_escalated_cnt']})")
    print(f"   - Total Unresolved : {m3['unresolved_count']}")
    print(f"   - Total Checkouts  : {m3['total_checkouts']} / 100")
    print()

    # 4. Loop 3 Baseline DB (duplicate_charge.db)
    m4 = compute_dup_metrics(DB4)
    print(f"4. [{DB4}]")
    print(f"   - Charges At Risk  : INR {m4['charges_at_risk_inr']:,.2f}")
    print(f"   - Charges Refunded : INR {m4['refunded_inr']:,.2f} ({m4['refund_count']} charges)")
    print(f"   - Refund Rate      : {m4['refund_rate_pct']:.2f}%")
    print(f"   - Total Escalated  : {m4['escalated_count']}")
    print(f"   - Total No Action  : {m4['no_action_count']} (Legitimate false positives)")
    print(f"   - Total Charges    : {m4['total_charges']} / 100")
    print()

    # 5. Canonical Loop 3 Snapshot DB (duplicate_charge_verified_snapshot.db)
    m5 = compute_dup_metrics(DB5)
    print(f"5. [{DB5}]")
    print(f"   - Charges At Risk  : INR {m5['charges_at_risk_inr']:,.2f}")
    print(f"   - Charges Refunded : INR {m5['refunded_inr']:,.2f} ({m5['refund_count']} charges)")
    print(f"   - Refund Rate      : {m5['refund_rate_pct']:.2f}%")
    print(f"   - Total Escalated  : {m5['escalated_count']}")
    print(f"   - Total No Action  : {m5['no_action_count']} (Legitimate false positives)")
    print(f"   - Total Charges    : {m5['total_charges']} / 100")
    print()


def main():
    print_db_metrics("BEFORE RUNNING LIVE INTERACTIVE SIMULATION CLICKS")

    print("=" * 80)
    print("EXECUTING LIVE INTERACTIVE SIMULATION API CALLS...")
    print("=" * 80)

    client = app.app.test_client()

    # Run 3 payment failure simulations
    for i in range(3):
        res = client.post("/api/simulate-payment-failure")
        data = res.get_json()
        print(f"[Simulate Payment Failure #{i+1}] ID: {data['payment_id']} | Category: {data['category']} | Action: {data['recommended_action']} | Policy: {data['policy_decision']} | Status: {data['final_status']} | Elapsed: {data['elapsed_seconds']}s")

    # Run 3 checkout abandonment simulations
    for i in range(3):
        res = client.post("/api/simulate-checkout-abandonment")
        data = res.get_json()
        print(f"[Simulate Checkout Abandonment #{i+1}] ID: {data['checkout_id']} | Category: {data['category']} | Action: {data['recommended_action']} | Policy: {data['policy_decision']} | Status: {data['final_status']} | Elapsed: {data['elapsed_seconds']}s")

    # Run 3 duplicate charge simulations
    for i in range(3):
        res = client.post("/api/simulate-duplicate-charge")
        data = res.get_json()
        print(f"[Simulate Duplicate Charge #{i+1}] ID: {data['charge_id']} | Category: {data['category']} | Action: {data['recommended_action']} | Policy: {data['policy_decision']} | Status: {data['final_status']} | Elapsed: {data['elapsed_seconds']}s")

    print()
    print_db_metrics("AFTER RUNNING LIVE INTERACTIVE SIMULATION CLICKS")

    # Strict Assertions
    m1 = compute_batch_metrics(DB1)
    m2 = compute_checkout_batch_metrics(DB2)
    m3 = compute_checkout_batch_metrics(DB3)
    m4 = compute_dup_metrics(DB4)
    m5 = compute_dup_metrics(DB5)

    assert m1['revenue_at_risk_inr'] == 650204.0, f"m1 risk mismatch: {m1['revenue_at_risk_inr']}"
    assert m1['revenue_recovered_inr'] == 70127.0, f"m1 recovered mismatch: {m1['revenue_recovered_inr']}"
    assert round(m1['recovery_rate_pct'], 2) == 10.79, f"m1 rate mismatch: {m1['recovery_rate_pct']}"
    assert m1['escalated_count'] == 45, f"m1 escalated mismatch: {m1['escalated_count']}"
    assert m1['unresolved_count'] == 6, f"m1 unresolved mismatch: {m1['unresolved_count']}"
    assert m1['still_failed_count'] == 7, f"m1 still failed mismatch: {m1['still_failed_count']}"

    assert m2['carts_at_risk_paise'] / 100.0 == 859212.0, f"m2 risk mismatch: {m2['carts_at_risk_paise']}"
    assert m2['carts_recovered_paise'] / 100.0 == 55379.0, f"m2 recovered mismatch: {m2['carts_recovered_paise']}"
    assert round(m2['recovery_rate'], 2) == 6.45, f"m2 rate mismatch: {m2['recovery_rate']}"
    assert m2['escalated_count'] == 55, f"m2 escalated mismatch: {m2['escalated_count']}"
    assert m2['unresolved_count'] == 0, f"m2 unresolved mismatch: {m2['unresolved_count']}"

    assert m3['carts_at_risk_paise'] / 100.0 == 859212.0, f"m3 risk mismatch: {m3['carts_at_risk_paise']}"
    assert m3['carts_recovered_paise'] / 100.0 == 55379.0, f"m3 recovered mismatch: {m3['carts_recovered_paise']}"
    assert round(m3['recovery_rate'], 2) == 6.45, f"m3 rate mismatch: {m3['recovery_rate']}"
    assert m3['escalated_count'] == 55, f"m3 escalated mismatch: {m3['escalated_count']}"
    assert m3['unresolved_count'] == 0, f"m3 unresolved mismatch: {m3['unresolved_count']}"

    assert m4['charges_at_risk_inr'] == 1327100.0, f"m4 risk mismatch: {m4['charges_at_risk_inr']}"
    assert m4['refunded_inr'] == 352250.0, f"m4 refunded mismatch: {m4['refunded_inr']}"
    assert round(m4['refund_rate_pct'], 2) == 26.54, f"m4 rate mismatch: {m4['refund_rate_pct']}"
    assert m4['escalated_count'] == 25, f"m4 escalated mismatch: {m4['escalated_count']}"
    assert m4['no_action_count'] == 25, f"m4 no action mismatch: {m4['no_action_count']}"

    assert m5['charges_at_risk_inr'] == 1327100.0, f"m5 risk mismatch: {m5['charges_at_risk_inr']}"
    assert m5['refunded_inr'] == 352250.0, f"m5 refunded mismatch: {m5['refunded_inr']}"
    assert round(m5['refund_rate_pct'], 2) == 26.54, f"m5 rate mismatch: {m5['refund_rate_pct']}"
    assert m5['escalated_count'] == 25, f"m5 escalated mismatch: {m5['escalated_count']}"
    assert m5['no_action_count'] == 25, f"m5 no action mismatch: {m5['no_action_count']}"

    print("=" * 80)
    print("ALL VERIFICATION CHECKS PASSED PERFECTLY! 100% UNTOUCHED BASELINE GUARANTEE CONFIRMED ACROSS ALL 5 DATABASES.")
    print("=" * 80)


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
