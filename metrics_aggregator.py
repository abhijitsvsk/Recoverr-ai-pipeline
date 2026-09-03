"""
Batch Metrics Aggregator for RecoverAI Payment Recovery Agent.
Calculates uncaptured revenue at risk, recovered revenue, category recovery rates,
and escalated/unresolved counts.
Includes post-processing modeled recovery-link conversion simulation.
"""

import random
from typing import Dict, Any, List

from db import get_connection, init_db
from action_executor import DEFAULT_RETRY_SUCCESS_RATE

DEFAULT_LINK_CONVERSION_RATE = 0.30  # Model assumption: ~30% modeled link conversion rate

LOOP1_PROBABILITY_MAP = {
    "RETRY": DEFAULT_RETRY_SUCCESS_RATE,                  # 0.70
    "SEND_RECOVERY_LINK": DEFAULT_LINK_CONVERSION_RATE,   # 0.30
    "ESCALATE": 0.0,
    "STOP": 0.0,
}

LOOP1_ACTION_REASON_MAP = {
    "RETRY": "automated retry attempted with modeled success probability 0.70",
    "SEND_RECOVERY_LINK": "recovery link generated with modeled conversion probability 0.30",
    "ESCALATE": "escalation — no automatic recovery probability modeled, outcome depends on human action",
    "STOP": "no action taken, no recovery expected",
}


def compute_and_store_loop1_ev(db_path: str = "recover_ai.db") -> Dict[str, Any]:
    """
    Compute expected_recovery_value_paise and recommended_expected_value_paise for all Loop 1 payments,
    and update payments table in SQLite.
    Formula: expected_recovery_value_paise = P(success | action_taken) * amount_in_paise
    """
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT p.id, p.amount_in_paise, p.status, p.recommended_action,
               a.action_taken
        FROM payments p
        LEFT JOIN audit_log a ON p.id = a.payment_id AND a.event_type = 'ACTION_EXECUTED';
        """
    )
    rows = cursor.fetchall()

    total_recommended_ev_paise = 0.0
    total_expected_ev_paise = 0.0
    records_computed = 0

    for r in rows:
        pid = r["id"]
        amt = r["amount_in_paise"]
        rec_act = r["recommended_action"]
        status = r["status"]
        act_taken = r["action_taken"]

        # 1. Recommended EV (LLM suggestion)
        rec_p = LOOP1_PROBABILITY_MAP.get(rec_act, 0.0) if rec_act else 0.0
        rec_ev = rec_p * amt

        # 2. Final Executed EV (Policy Engine / final action)
        if status in ("ESCALATED", "STOPPED") or not act_taken or act_taken in ("ESCALATE", "STOP"):
            final_p = 0.0
        else:
            final_p = LOOP1_PROBABILITY_MAP.get(act_taken, 0.0)

        final_ev = final_p * amt

        cursor.execute(
            """
            UPDATE payments
            SET recommended_expected_value_paise = ?,
                expected_recovery_value_paise = ?
            WHERE id = ?;
            """,
            (rec_ev, final_ev, pid),
        )

        total_recommended_ev_paise += rec_ev
        total_expected_ev_paise += final_ev
        records_computed += 1

    conn.commit()
    conn.close()

    return {
        "records_computed": records_computed,
        "total_recommended_ev_paise": total_recommended_ev_paise,
        "total_recommended_ev_inr": total_recommended_ev_paise / 100.0,
        "total_expected_ev_paise": total_expected_ev_paise,
        "total_expected_ev_inr": total_expected_ev_paise / 100.0,
    }


# Recovery link conversion is simulated for the MVP demo (~30% modeled conversion rate).
# Real customer conversion requires user interaction on the recovery link, which is out of
# scope for synthetic batch evaluation. This is a documented modeling assumption, not a real result.
def simulate_link_conversions(
    db_path: str = "recover_ai.db", conversion_rate: float = DEFAULT_LINK_CONVERSION_RATE
) -> Dict[str, bool]:
    """
    Simulate recovery link conversion outcomes using a deterministic random function seeded by payment_id.
    Plausible modeled conversion rate is ~30%.
    Returns a dict mapping payment_id -> recovery_confirmed (True/False).
    Does NOT overwrite original business_outcome='link_sent'.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT p.id
        FROM payments p
        JOIN audit_log a ON p.id = a.payment_id AND a.event_type = 'ACTION_EXECUTED'
        WHERE a.action_taken = 'SEND_RECOVERY_LINK' AND a.business_outcome = 'link_sent';
        """
    )
    rows = cursor.fetchall()
    conn.close()

    conversions = {}
    for r in rows:
        pid = r["id"]
        rng = random.Random(f"link_conversion_{pid}")
        conversions[pid] = rng.random() < conversion_rate

    return conversions


def compute_batch_metrics(
    db_path: str = "recover_ai.db", conversion_rate: float = DEFAULT_LINK_CONVERSION_RATE
) -> Dict[str, Any]:
    """
    Compute full batch metrics across all 100 payments according to exact product definitions.
    """
    link_conversions = simulate_link_conversions(db_path, conversion_rate)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Fetch all payments with action execution logs
    cursor.execute(
        """
        SELECT p.id, p.category, p.amount_in_paise, p.status, p.recommended_action,
               a.execution_result, a.business_outcome
        FROM payments p
        LEFT JOIN audit_log a ON p.id = a.payment_id AND a.event_type = 'ACTION_EXECUTED';
        """
    )
    payment_rows = cursor.fetchall()

    # Fetch policy decision audit log for sub-breakdown of escalated payments
    cursor.execute(
        """
        SELECT payment_id, policy_decision, policy_reason
        FROM audit_log
        WHERE event_type = 'POLICY_DECISION';
        """
    )
    policy_logs = {r["payment_id"]: r["policy_decision"] for r in cursor.fetchall()}
    conn.close()

    revenue_at_risk_paise = sum(r["amount_in_paise"] for r in payment_rows)
    revenue_recovered_paise = 0

    retry_recovered_count = 0
    link_recovered_count = 0
    link_unconverted_count = 0
    still_failed_count = 0
    unresolved_count = 0

    escalated_blocked_count = 0
    escalated_approved_count = 0

    overlap_count = 0

    category_breakdown = {
        "TEMPORARY": {"count": 0, "at_risk_paise": 0, "recovered_paise": 0},
        "PERMANENT": {"count": 0, "at_risk_paise": 0, "recovered_paise": 0},
        "REPEATED_FAILURE": {"count": 0, "at_risk_paise": 0, "recovered_paise": 0},
        "UNKNOWN": {"count": 0, "at_risk_paise": 0, "recovered_paise": 0},
    }

    for r in payment_rows:
        pid = r["id"]
        cat = r["category"]
        amt = r["amount_in_paise"]
        status = r["status"]
        action = r["recommended_action"]
        bus_out = r["business_outcome"]
        pol_dec = policy_logs.get(pid)

        target_cat = cat if (cat and cat in category_breakdown) else "UNKNOWN"
        category_breakdown[target_cat]["count"] += 1
        category_breakdown[target_cat]["at_risk_paise"] += amt

        is_recovered = False
        if action == "RETRY" and bus_out == "recovered":
            is_recovered = True
            retry_recovered_count += 1
        elif action == "SEND_RECOVERY_LINK" and link_conversions.get(pid, False):
            is_recovered = True
            link_recovered_count += 1
        elif action == "SEND_RECOVERY_LINK" and not link_conversions.get(pid, False):
            link_unconverted_count += 1

        if is_recovered:
            revenue_recovered_paise += amt
            category_breakdown[target_cat]["recovered_paise"] += amt
            if status in ("ESCALATED", "STOPPED"):
                overlap_count += 1

        if status == "FAILED_EXECUTION":
            still_failed_count += 1
        elif status == "STOPPED":
            unresolved_count += 1
        elif status == "ESCALATED":
            if pol_dec == "BLOCKED":
                escalated_blocked_count += 1
            else:
                escalated_approved_count += 1

    escalated_count = escalated_blocked_count + escalated_approved_count

    recovery_rate_pct = (
        (revenue_recovered_paise / revenue_at_risk_paise * 100.0)
        if revenue_at_risk_paise > 0
        else 0.0
    )

    # Compute category rates
    for cat, d in category_breakdown.items():
        d["at_risk_inr"] = d["at_risk_paise"] / 100.0
        d["recovered_inr"] = d["recovered_paise"] / 100.0
        d["recovery_rate_pct"] = (
            (d["recovered_paise"] / d["at_risk_paise"] * 100.0)
            if d["at_risk_paise"] > 0
            else 0.0
        )

    sum_check_total = (
        retry_recovered_count
        + link_recovered_count
        + link_unconverted_count
        + still_failed_count
        + escalated_count
        + unresolved_count
    )

    # Ensure EV scoring layer is computed and stored on payments table
    ev_summary = compute_and_store_loop1_ev(db_path)

    return {
        "total_batch_records": len(payment_rows),
        "link_sent_total": len(link_conversions),
        "link_converted_count": link_recovered_count,
        "link_unconverted_count": link_unconverted_count,
        "revenue_at_risk_paise": revenue_at_risk_paise,
        "revenue_at_risk_inr": revenue_at_risk_paise / 100.0,
        "revenue_recovered_paise": revenue_recovered_paise,
        "revenue_recovered_inr": revenue_recovered_paise / 100.0,
        "total_expected_ev_paise": ev_summary["total_expected_ev_paise"],
        "total_expected_ev_inr": ev_summary["total_expected_ev_inr"],
        "total_recommended_ev_paise": ev_summary["total_recommended_ev_paise"],
        "total_recommended_ev_inr": ev_summary["total_recommended_ev_inr"],
        "recovery_rate_pct": recovery_rate_pct,
        "recovery_rate_definition": "(revenue_recovered_paise / revenue_at_risk_paise) * 100",
        "escalated_count": escalated_count,
        "escalated_subbreakdown": {
            "blocked_then_escalated": escalated_blocked_count,
            "recommended_and_approved_escalated": escalated_approved_count,
        },
        "unresolved_count": unresolved_count,
        "still_failed_count": still_failed_count,
        "retry_recovered_count": retry_recovered_count,
        "category_breakdown": category_breakdown,
        "reconciliation": {
            "sum_check_total": sum_check_total,
            "is_sum_exact_100": sum_check_total == 100,
            "overlap_count": overlap_count,
            "is_zero_overlap": overlap_count == 0,
        },
    }
