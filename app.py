"""
Flask Web Dashboard for RecoverAI Payment Recovery Agent.
Read-only display layer presenting batch evaluation metrics, category breakdowns,
recovery action table, and step-by-step audit timelines.
"""

import os
import sqlite3
from flask import Flask, jsonify, render_template, request

from db import get_connection, restore_snapshot
from metrics_aggregator import compute_batch_metrics, simulate_link_conversions

from checkout_db import get_checkout_connection
from checkout_metrics_aggregator import compute_checkout_batch_metrics, simulate_checkout_conversions

app = Flask(__name__, template_folder="templates", static_folder="static")
DB_PATH = "recover_ai.db"
SNAPSHOT_PATH = "recover_ai_verified_snapshot.db"
CHECKOUT_DB_PATH = "checkout_recovery.db"


@app.route("/")
def index():
    demo_mode = os.environ.get("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    return render_template("index.html", demo_mode=demo_mode)


@app.route("/api/reset", methods=["POST"])
def reset_database():
    """Fast recording reset endpoint restoring database from pre-computed verified snapshot (<10ms)."""
    try:
        restore_snapshot(SNAPSHOT_PATH, DB_PATH)
        return jsonify({"status": "success", "message": "Database successfully restored from verified snapshot."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/metrics")
def get_metrics():
    metrics = compute_batch_metrics(DB_PATH)
    return jsonify(metrics)


@app.route("/api/payments")
def get_payments():
    category_filter = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()

    link_conversions = simulate_link_conversions(DB_PATH)

    conn = get_connection(DB_PATH)
    cursor = conn.cursor()

    query = """
        SELECT p.id, p.amount_in_paise, p.failure_reason, p.ground_truth_category,
               p.category, p.status, p.attempt_count, p.last_attempt_at,
               p.recommended_action, p.recommendation_reason,
               a.execution_result, a.business_outcome,
               pol.policy_decision, pol.policy_reason
        FROM payments p
        LEFT JOIN audit_log a ON p.id = a.payment_id AND a.event_type = 'ACTION_EXECUTED'
        LEFT JOIN audit_log pol ON p.id = pol.payment_id AND pol.event_type = 'POLICY_DECISION';
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    payments = []
    for r in rows:
        pid = r["id"]
        cat = r["category"]
        st = r["status"]

        if category_filter and category_filter.upper() != "ALL" and cat != category_filter.upper():
            continue
        if status_filter and status_filter.upper() != "ALL" and st != status_filter.upper():
            continue

        rec_confirmed = False
        if r["recommended_action"] == "SEND_RECOVERY_LINK" and link_conversions.get(pid, False):
            rec_confirmed = True

        payments.append({
            "payment_id": pid,
            "amount_in_paise": r["amount_in_paise"],
            "amount_in_inr": r["amount_in_paise"] / 100.0,
            "failure_reason": r["failure_reason"],
            "category": cat,
            "attempt_count": r["attempt_count"],
            "status": st,
            "recommended_action": r["recommended_action"],
            "recommendation_reason": r["recommendation_reason"],
            "policy_decision": r["policy_decision"],
            "policy_reason": r["policy_reason"],
            "execution_result": r["execution_result"],
            "business_outcome": r["business_outcome"],
            "recovery_confirmed": rec_confirmed,
        })

    return jsonify(payments)


@app.route("/api/payments/<payment_id>/timeline")
def get_payment_timeline(payment_id):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, event_id, event_type, attempt_number, timestamp,
               category, recommended_action, policy_decision, policy_reason,
               action_taken, execution_result, business_outcome, amount_in_paise
        FROM audit_log
        WHERE payment_id = ?
        ORDER BY timestamp ASC, id ASC;
    """, (payment_id,))
    rows = cursor.fetchall()
    conn.close()

    timeline = []
    for r in rows:
        timeline.append({
            "id": r["id"],
            "event_id": r["event_id"],
            "event_type": r["event_type"],
            "attempt_number": r["attempt_number"],
            "timestamp": r["timestamp"],
            "category": r["category"],
            "recommended_action": r["recommended_action"],
            "policy_decision": r["policy_decision"],
            "policy_reason": r["policy_reason"],
            "action_taken": r["action_taken"],
            "execution_result": r["execution_result"],
            "business_outcome": r["business_outcome"],
            "amount_in_paise": r["amount_in_paise"],
            "amount_in_inr": r["amount_in_paise"] / 100.0,
        })

    return jsonify(timeline)


# ==============================================================================
# LOOP 2: CHECKOUT ABANDONMENT ENDPOINTS
# ==============================================================================

@app.route("/api/checkout-metrics")
def get_checkout_metrics():
    simulate_checkout_conversions(CHECKOUT_DB_PATH)
    metrics = compute_checkout_batch_metrics(CHECKOUT_DB_PATH)
    metrics["carts_at_risk_inr"] = metrics["carts_at_risk_paise"] / 100.0
    metrics["carts_recovered_inr"] = metrics["carts_recovered_paise"] / 100.0
    for cat, m in metrics["category_metrics"].items():
        m["at_risk_inr"] = m["at_risk_paise"] / 100.0
        m["recovered_inr"] = m["recovered_paise"] / 100.0
    return jsonify(metrics)


@app.route("/api/checkouts")
def get_checkouts():
    category_filter = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()

    simulate_checkout_conversions(CHECKOUT_DB_PATH)

    conn = get_checkout_connection(CHECKOUT_DB_PATH)
    cursor = conn.cursor()

    query = """
        SELECT c.id, c.cart_value_in_paise, c.customer_abandon_reason, c.expected_category,
               c.category, c.status, c.abandon_count, c.abandoned_at,
               c.recommended_action, c.recommendation_reason, c.policy_decision, c.policy_reason,
               c.cart_recovery_confirmed,
               a.action_taken, a.execution_result, a.business_outcome
        FROM checkouts c
        LEFT JOIN checkout_audit_log a ON c.id = a.checkout_id AND a.event_type = 'ACTION_EXECUTED';
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    checkouts = []
    for r in rows:
        cid = r["id"]
        cat = r["category"]
        st = r["status"]

        if category_filter and category_filter.upper() != "ALL" and cat != category_filter.upper():
            continue
        if status_filter and status_filter.upper() != "ALL" and st != status_filter.upper():
            continue

        checkouts.append({
            "checkout_id": cid,
            "cart_value_in_paise": r["cart_value_in_paise"],
            "cart_value_in_inr": r["cart_value_in_paise"] / 100.0,
            "customer_abandon_reason": r["customer_abandon_reason"],
            "category": cat,
            "abandon_count": r["abandon_count"],
            "abandoned_at": r["abandoned_at"],
            "status": st,
            "recommended_action": r["recommended_action"],
            "recommendation_reason": r["recommendation_reason"],
            "policy_decision": r["policy_decision"],
            "policy_reason": r["policy_reason"],
            "action_taken": r["action_taken"],
            "execution_result": r["execution_result"],
            "business_outcome": r["business_outcome"],
            "cart_recovery_confirmed": bool(r["cart_recovery_confirmed"]),
        })

    return jsonify(checkouts)


@app.route("/api/checkouts/<checkout_id>/timeline")
def get_checkout_timeline(checkout_id):
    conn = get_checkout_connection(CHECKOUT_DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT a.id, a.event_id, a.event_type, a.timestamp,
               a.category, a.recommended_action, a.policy_decision, a.policy_reason,
               a.action_taken, a.execution_result, a.business_outcome, a.cart_value_in_paise,
               c.cart_recovery_confirmed
        FROM checkout_audit_log a
        JOIN checkouts c ON a.checkout_id = c.id
        WHERE a.checkout_id = ?
        ORDER BY a.timestamp ASC, a.id ASC;
    """, (checkout_id,))
    rows = cursor.fetchall()
    conn.close()

    timeline = []
    for r in rows:
        timeline.append({
            "id": r["id"],
            "event_id": r["event_id"],
            "event_type": r["event_type"],
            "timestamp": r["timestamp"],
            "category": r["category"],
            "recommended_action": r["recommended_action"],
            "policy_decision": r["policy_decision"],
            "policy_reason": r["policy_reason"],
            "action_taken": r["action_taken"],
            "execution_result": r["execution_result"],
            "business_outcome": r["business_outcome"],
            "cart_value_in_paise": r["cart_value_in_paise"],
            "cart_value_in_inr": r["cart_value_in_paise"] / 100.0,
            "cart_recovery_confirmed": bool(r["cart_recovery_confirmed"]),
        })

    return jsonify(timeline)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

