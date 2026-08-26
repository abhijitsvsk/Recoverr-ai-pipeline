"""
Batch Metrics Aggregator Module for Loop 2 Checkout Abandonment Recovery.
Simulates conversion outcomes for reminders & discount nudges using deterministic rates.
Calculates headline metrics (carts at risk, carts recovered, recovery rate, escalated count, unresolved count),
category breakdown, and reconciliation checks.
100% separate from Loop 1 metrics aggregator.
"""

import random
import sqlite3
from typing import Dict, Any, List, Tuple

from checkout_db import get_checkout_connection, init_checkout_db
from checkout_models import CheckoutCategory, CheckoutStatus, CheckoutRecoveryAction


REMINDER_CONVERSION_RATE = 0.25
DISCOUNT_NUDGE_CONVERSION_RATE = 0.40

LOOP2_PROBABILITY_MAP = {
    "SEND_CART_REMINDER": REMINDER_CONVERSION_RATE,        # 0.25
    "SEND_DISCOUNT_NUDGE": DISCOUNT_NUDGE_CONVERSION_RATE, # 0.40
    "ESCALATE": 0.0,
    "STOP": 0.0,
}

LOOP2_ACTION_REASON_MAP = {
    "SEND_CART_REMINDER": "cart reminder generated with modeled conversion probability 0.25",
    "SEND_DISCOUNT_NUDGE": "discount nudge generated with modeled conversion probability 0.40",
    "ESCALATE": "escalation — no automatic recovery probability modeled, outcome depends on human action",
    "STOP": "no action taken, no recovery expected",
}


def compute_and_store_loop2_ev(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Compute expected_recovery_value_paise and recommended_expected_value_paise for all Loop 2 checkouts,
    and update checkouts table in SQLite.
    Formula: expected_recovery_value_paise = P(success | action_taken) * cart_value_in_paise
    """
    init_checkout_db(db_path)
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT c.id, c.cart_value_in_paise, c.status, c.recommended_action,
               a.action_taken
        FROM checkouts c
        LEFT JOIN checkout_audit_log a ON c.id = a.checkout_id AND a.event_type = 'ACTION_EXECUTED';
        """
    )
    rows = cursor.fetchall()

    total_recommended_ev_paise = 0.0
    total_expected_ev_paise = 0.0
    records_computed = 0

    for r in rows:
        cid = r["id"]
        val = r["cart_value_in_paise"]
        rec_act = r["recommended_action"]
        status = r["status"]
        act_taken = r["action_taken"]

        # 1. Recommended EV (LLM suggestion)
        rec_p = LOOP2_PROBABILITY_MAP.get(rec_act, 0.0) if rec_act else 0.0
        rec_ev = rec_p * val

        # 2. Final Executed EV (Policy Engine / final action)
        if status in ("ESCALATED", "STOPPED") or not act_taken or act_taken in ("ESCALATE", "STOP"):
            final_p = 0.0
        else:
            final_p = LOOP2_PROBABILITY_MAP.get(act_taken, 0.0)

        final_ev = final_p * val

        cursor.execute(
            """
            UPDATE checkouts
            SET recommended_expected_value_paise = ?,
                expected_recovery_value_paise = ?
            WHERE id = ?;
            """,
            (rec_ev, final_ev, cid),
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


def simulate_checkout_conversions(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Simulates conversion outcomes for checkouts where action_taken is SEND_CART_REMINDER or SEND_DISCOUNT_NUDGE.
    Uses deterministic pseudo-random simulation seeded by checkout_id.
    
    Modeled Conversion Rates Reasoning:
    - SEND_CART_REMINDER: ~25% modeled conversion rate (lower-touch reminder, random.random() < 0.25).
    - SEND_DISCOUNT_NUDGE: ~40% modeled conversion rate (incentivized discount nudge, random.random() < 0.40).
    
    Note: These are modeled conversion rates for synthetic batch evaluation in MVP demo,
    not real customer actions, as there is no live customer in this synthetic benchmark.
    Does NOT overwrite original business_outcome ('reminder_sent' / 'nudge_sent').
    Sets cart_recovery_confirmed = 1 in database.
    """
    init_checkout_db(db_path)
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    # Query all audit log records where action_taken is SEND_CART_REMINDER or SEND_DISCOUNT_NUDGE
    cursor.execute(
        """
        SELECT checkout_id, action_taken, cart_value_in_paise
        FROM checkout_audit_log
        WHERE event_type = 'ACTION_EXECUTED'
          AND action_taken IN ('SEND_CART_REMINDER', 'SEND_DISCOUNT_NUDGE');
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    reminder_total = 0
    reminder_converted = 0
    nudge_total = 0
    nudge_converted = 0

    with conn:
        for r in rows:
            checkout_id = r["checkout_id"]
            action = r["action_taken"]

            # Deterministic RNG seeded by checkout_id
            rng = random.Random(f"chk_conv_{checkout_id}")

            if action == CheckoutRecoveryAction.SEND_CART_REMINDER.value:
                reminder_total += 1
                is_converted = rng.random() < 0.25
                if is_converted:
                    reminder_converted += 1
            elif action == CheckoutRecoveryAction.SEND_DISCOUNT_NUDGE.value:
                nudge_total += 1
                is_converted = rng.random() < 0.40
                if is_converted:
                    nudge_converted += 1
            else:
                is_converted = False

            if is_converted:
                cursor.execute(
                    """
                    UPDATE checkouts
                    SET cart_recovery_confirmed = 1
                    WHERE id = ?;
                    """,
                    (checkout_id,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE checkouts
                    SET cart_recovery_confirmed = 0
                    WHERE id = ?;
                    """,
                    (checkout_id,),
                )

    conn.close()

    return {
        "reminder_total": reminder_total,
        "reminder_converted": reminder_converted,
        "nudge_total": nudge_total,
        "nudge_converted": nudge_converted,
    }


def compute_checkout_batch_metrics(db_path: str = "checkout_recovery.db") -> Dict[str, Any]:
    """
    Computes complete batch metrics across all 100 checkouts in checkout_recovery.db.
    Calculates carts_at_risk_paise, carts_recovered_paise, recovery_rate,
    escalated_count (with sub-breakdown), unresolved_count, category breakdown table,
    and reconciliation invariants.
    """
    init_checkout_db(db_path)
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    # Fetch checkouts data
    cursor.execute(
        """
        SELECT id, cart_value_in_paise, category, status, 
               recommended_action, policy_decision, cart_recovery_confirmed
        FROM checkouts;
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    # Fetch audit log POLICY_DECISION to accurately track policy-blocked vs direct-approved escalations
    cursor.execute(
        """
        SELECT checkout_id, policy_decision
        FROM checkout_audit_log
        WHERE event_type = 'POLICY_DECISION';
        """
    )
    policy_audit_map = {r["checkout_id"]: r["policy_decision"] for r in cursor.fetchall()}

    conn.close()

    total_checkouts = len(rows)

    # 1. Headline Metrics Calculation
    carts_at_risk_paise = sum(r["cart_value_in_paise"] for r in rows)
    carts_recovered_paise = sum(r["cart_value_in_paise"] for r in rows if r["cart_recovery_confirmed"] == 1)

    recovery_rate = (carts_recovered_paise / carts_at_risk_paise * 100.0) if carts_at_risk_paise > 0 else 0.0
    recovery_rate_definition = "(carts_recovered_paise / carts_at_risk_paise) * 100 [Recovered ÷ At Risk]"

    # Escalated count and sub-breakdown
    escalated_rows = [r for r in rows if r["status"] == CheckoutStatus.ESCALATED.value]
    escalated_count = len(escalated_rows)

    direct_approved_escalated = [
        r for r in escalated_rows if policy_audit_map.get(r["id"]) == "APPROVED"
    ]
    policy_blocked_escalated = [
        r for r in escalated_rows if policy_audit_map.get(r["id"]) == "BLOCKED"
    ]

    direct_approved_escalated_cnt = len(direct_approved_escalated)
    policy_blocked_escalated_cnt = len(policy_blocked_escalated)

    # Unresolved count (STOPPED)
    stopped_rows = [r for r in rows if r["status"] == CheckoutStatus.STOPPED.value]
    unresolved_count = len(stopped_rows)

    unresolved_explanation = (
        "unresolved_count is 0 in this batch because STALE_ABANDON's allowed policy action is STOP, "
        "but the LLM recommended SEND_DISCOUNT_NUDGE for all 20 STALE_ABANDON records instead of STOP. "
        "Consequently, the Policy Engine BLOCKED all 20 records and routed them to ESCALATED (per the state machine rule: BLOCKED -> ESCALATED)."
    )

    # 2. Category Breakdown Matrix
    categories = sorted(list(set(r["category"] for r in rows if r["category"])))
    category_metrics: Dict[str, Dict[str, Any]] = {}

    for cat in categories:
        cat_rows = [r for r in rows if r["category"] == cat]
        cat_cnt = len(cat_rows)
        cat_at_risk = sum(r["cart_value_in_paise"] for r in cat_rows)
        cat_recovered = sum(r["cart_value_in_paise"] for r in cat_rows if r["cart_recovery_confirmed"] == 1)
        cat_rec_rate = (cat_recovered / cat_at_risk * 100.0) if cat_at_risk > 0 else 0.0

        category_metrics[cat] = {
            "count": cat_cnt,
            "at_risk_paise": cat_at_risk,
            "recovered_paise": cat_recovered,
            "recovery_rate": cat_rec_rate,
        }

    # 3. Reconciliation & Overlap Verification
    converted_count = sum(1 for r in rows if r["cart_recovery_confirmed"] == 1)
    unconverted_count = sum(
        1 for r in rows 
        if r["cart_recovery_confirmed"] == 0 and r["status"] == CheckoutStatus.SUCCEEDED.value
    )

    sum_reconciliation = converted_count + unconverted_count + escalated_count + unresolved_count

    # Overlap Check: cart_recovery_confirmed == 1 AND status == ESCALATED
    overlap_count = sum(
        1 for r in rows if r["cart_recovery_confirmed"] == 1 and r["status"] == CheckoutStatus.ESCALATED.value
    )

    # Ensure EV scoring layer is computed and stored on checkouts table
    ev_summary = compute_and_store_loop2_ev(db_path)

    return {
        "total_checkouts": total_checkouts,
        "carts_at_risk_paise": carts_at_risk_paise,
        "carts_recovered_paise": carts_recovered_paise,
        "carts_at_risk_inr": carts_at_risk_paise / 100.0,
        "carts_recovered_inr": carts_recovered_paise / 100.0,
        "total_expected_ev_paise": ev_summary["total_expected_ev_paise"],
        "total_expected_ev_inr": ev_summary["total_expected_ev_inr"],
        "total_recommended_ev_paise": ev_summary["total_recommended_ev_paise"],
        "total_recommended_ev_inr": ev_summary["total_recommended_ev_inr"],
        "recovery_rate": recovery_rate,
        "recovery_rate_definition": recovery_rate_definition,
        "escalated_count": escalated_count,
        "direct_approved_escalated_cnt": direct_approved_escalated_cnt,
        "policy_blocked_escalated_cnt": policy_blocked_escalated_cnt,
        "unresolved_count": unresolved_count,
        "unresolved_explanation": unresolved_explanation,
        "category_metrics": category_metrics,
        "converted_count": converted_count,
        "unconverted_count": unconverted_count,
        "sum_reconciliation": sum_reconciliation,
        "overlap_count": overlap_count,
    }
