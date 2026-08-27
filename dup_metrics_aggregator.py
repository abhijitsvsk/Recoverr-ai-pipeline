"""
Batch Metrics Aggregator for Loop 3: Duplicate Charge Detection & Auto-Refund.
Calculates financial reconciliation, refund rates, Expected Value (EV), and false-positive handling metrics.
"""

from typing import Dict, Any
from dup_db import get_dup_connection
from dup_models import DupCategory, DupAction, DupStatus


def compute_dup_metrics(db_path: str = "duplicate_charge.db") -> Dict[str, Any]:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, amount_in_paise, category, status, action_taken, business_outcome, policy_decision
        FROM duplicate_charges;
    """)
    rows = cursor.fetchall()

    total_charges = len(rows)
    charges_at_risk_paise = sum(r["amount_in_paise"] for r in rows)

    refunded_rows = [r for r in rows if r["status"] == DupStatus.SUCCEEDED.value]
    refunded_paise = sum(r["amount_in_paise"] for r in refunded_rows)
    refund_count = len(refunded_rows)

    escalated_rows = [r for r in rows if r["status"] == DupStatus.ESCALATED.value]
    escalated_count = len(escalated_rows)

    no_action_rows = [r for r in rows if r["status"] == DupStatus.NO_ACTION_TAKEN.value]
    no_action_count = len(no_action_rows)

    unrelated_rows = [r for r in rows if r["category"] == DupCategory.UNRELATED.value]
    unrelated_count = len(unrelated_rows)
    correct_false_positives = len([r for r in unrelated_rows if r["status"] == DupStatus.NO_ACTION_TAKEN.value])

    category_counts = {}
    for r in rows:
        cat = r["category"] or "UNCLASSIFIED"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    refund_rate_pct = (refunded_paise / charges_at_risk_paise * 100.0) if charges_at_risk_paise > 0 else 0.0

    # EV Calculation ($EV = P(refund | category, action) * amount)
    expected_refund_val_paise = 0
    for r in rows:
        act = r["action_taken"]
        amt = r["amount_in_paise"]
        if act == DupAction.AUTO_REFUND.value:
            prob = 0.95  # 95% model assumption for auto-refund success
        else:
            prob = 0.0
        expected_refund_val_paise += int(amt * prob)

    conn.close()

    return {
        "total_charges": total_charges,
        "charges_at_risk_paise": charges_at_risk_paise,
        "charges_at_risk_inr": charges_at_risk_paise / 100.0,
        "refunded_paise": refunded_paise,
        "refunded_inr": refunded_paise / 100.0,
        "refund_count": refund_count,
        "refund_rate_pct": round(refund_rate_pct, 2),
        "escalated_count": escalated_count,
        "no_action_count": no_action_count,
        "unrelated_false_positives_count": unrelated_count,
        "correctly_handled_false_positives": correct_false_positives,
        "category_counts": category_counts,
        "expected_refund_value_inr": expected_refund_val_paise / 100.0,
    }
