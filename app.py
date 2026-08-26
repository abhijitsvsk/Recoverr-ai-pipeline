"""
Flask Web Dashboard for RecoverAI Payment Recovery Agent.
Read-only display layer presenting batch evaluation metrics, category breakdowns,
recovery action table, and step-by-step audit timelines.
Includes live interactive simulation endpoints with strict DB isolation.
"""

import os
import time
import random
import sqlite3
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request

import db
from db import get_connection, restore_snapshot
from metrics_aggregator import compute_batch_metrics, simulate_link_conversions
import classifier
import llm_recommender
import policy_engine
import action_executor

import checkout_db
from checkout_db import get_checkout_connection, init_checkout_db
from checkout_metrics_aggregator import compute_checkout_batch_metrics, simulate_checkout_conversions
import checkout_classifier
import checkout_recommender
import checkout_policy_engine
import checkout_action_executor

app = Flask(__name__, template_folder="templates", static_folder="static")

# Protected Baseline Databases (NEVER written to by interactive live simulations)
DB_PATH = "recover_ai.db"
SNAPSHOT_PATH = "recover_ai_verified_snapshot.db"
CHECKOUT_DB_PATH = "checkout_recovery.db"

# Dedicated Live Simulation Databases
LIVE_TEST_DB_PATH = "recover_ai_live_test.db"
LIVE_TEST_CHECKOUT_DB_PATH = "checkout_recovery_live_test.db"


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

    if not rows and os.path.exists(LIVE_TEST_DB_PATH):
        conn = get_connection(LIVE_TEST_DB_PATH)
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

    if not rows and os.path.exists(LIVE_TEST_CHECKOUT_DB_PATH):
        conn = get_checkout_connection(LIVE_TEST_CHECKOUT_DB_PATH)
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


# ==============================================================================
# INTERACTIVE SIMULATION ENDPOINTS (STRICT LIVE TEST DB ISOLATION)
# ==============================================================================

@app.route("/api/simulate-payment-failure", methods=["POST"])
def simulate_payment_failure():
    """
    Simulate a new payment failure record in recover_ai_live_test.db ONLY.
    Guarantees recover_ai.db and recover_ai_verified_snapshot.db remain 100% untouched.
    """
    start_t = time.perf_counter()
    db_path = LIVE_TEST_DB_PATH
    db.init_db(db_path)

    reasons = ["gateway_error", "bank_declined", "card_expired", "insufficient_funds", "unmapped_network_drop_99"]
    amounts = [49900, 89900, 1250000, 1500000]
    failure_reason = random.choice(reasons)
    amount_in_paise = random.choice(amounts)
    attempt_count = random.choice([1, 1, 1, 3])

    payment_id = f"pay_sim_{int(time.time())}_{random.randint(100, 999)}"
    now_str = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO payments (
            id, amount_in_paise, failure_reason, ground_truth_category, category, status, attempt_count, last_attempt_at, created_at, updated_at
        ) VALUES (?, ?, ?, 'UNKNOWN', NULL, 'FAILED', ?, ?, ?, ?);
    """, (payment_id, amount_in_paise, failure_reason, attempt_count, now_str, now_str, now_str))

    cursor.execute("""
        INSERT INTO audit_log (
            id, event_id, event_type, payment_id, attempt_number, timestamp, amount_in_paise
        ) VALUES (?, ?, 'PAYMENT_FAILED', ?, ?, ?, ?);
    """, (f"aud_fail_{payment_id}", f"evt_fail_{payment_id}", payment_id, attempt_count, now_str, amount_in_paise))

    cursor.execute("""
        INSERT INTO idempotency (event_id, payment_id, processed_at) VALUES (?, ?, ?);
    """, (f"evt_fail_{payment_id}", payment_id, now_str))

    conn.commit()
    conn.close()

    # Process through pipeline on simulation DB
    classifier.process_classification_pipeline(db_path)
    llm_recommender.process_recommendation_pipeline(db_path)
    policy_engine.process_policy_pipeline(db_path)
    action_executor.process_action_pipeline(db_path)

    elapsed_s = round(time.perf_counter() - start_t, 2)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.category, p.recommended_action, p.recommendation_reason, p.status,
               pol.policy_decision, pol.policy_reason,
               act.action_taken, act.execution_result, act.business_outcome
        FROM payments p
        LEFT JOIN audit_log pol ON p.id = pol.payment_id AND pol.event_type = 'POLICY_DECISION'
        LEFT JOIN audit_log act ON p.id = act.payment_id AND act.event_type = 'ACTION_EXECUTED'
        WHERE p.id = ?;
    """, (payment_id,))
    r = cursor.fetchone()
    conn.close()

    return jsonify({
        "status": "success",
        "payment_id": payment_id,
        "elapsed_seconds": elapsed_s,
        "category": r["category"] if r else "UNKNOWN",
        "recommended_action": r["recommended_action"] if r else "NONE",
        "recommendation_reason": r["recommendation_reason"] if r else "",
        "policy_decision": r["policy_decision"] if r else "UNKNOWN",
        "policy_reason": r["policy_reason"] if r else "",
        "action_taken": r["action_taken"] if r else "NONE",
        "execution_result": r["execution_result"] if r else "NONE",
        "business_outcome": r["business_outcome"] if r else "NONE",
        "final_status": r["status"] if r else "UNKNOWN"
    })


@app.route("/api/simulate-checkout-abandonment", methods=["POST"])
def simulate_checkout_abandonment():
    """
    Simulate a new checkout abandonment record in checkout_recovery_live_test.db ONLY.
    Guarantees checkout_recovery.db and checkout_recovery_verified_snapshot.db remain 100% untouched.
    """
    start_t = time.perf_counter()
    db_path = LIVE_TEST_CHECKOUT_DB_PATH
    init_checkout_db(db_path)

    reasons = ["cart_idle_15m", "shipping_cost_too_high", "cart_idle_48h", "price_check_behavior", "unmapped_device_glitch_99"]
    cart_values = [299900, 499900, 1200000, 1500000]
    abandon_reason = random.choice(reasons)
    cart_value_in_paise = random.choice(cart_values)
    abandon_count = random.choice([1, 1, 2])

    checkout_id = f"chk_sim_{int(time.time())}_{random.randint(100, 999)}"
    now_str = datetime.now(timezone.utc).isoformat()

    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO checkouts (
            id, cart_value_in_paise, customer_abandon_reason, expected_category, category, abandon_count, status, abandoned_at, created_at, updated_at
        ) VALUES (?, ?, ?, 'UNKNOWN_ABANDON', NULL, ?, 'ABANDONED', ?, ?, ?);
    """, (checkout_id, cart_value_in_paise, abandon_reason, abandon_count, now_str, now_str, now_str))

    cursor.execute("""
        INSERT INTO checkout_audit_log (
            id, event_id, event_type, checkout_id, timestamp, cart_value_in_paise
        ) VALUES (?, ?, 'CHECKOUT_ABANDONED', ?, ?, ?);
    """, (f"aud_abnd_{checkout_id}", f"evt_abnd_{checkout_id}", checkout_id, now_str, cart_value_in_paise))

    cursor.execute("""
        INSERT INTO checkout_idempotency (event_id, checkout_id, processed_at) VALUES (?, ?, ?);
    """, (f"evt_abnd_{checkout_id}", checkout_id, now_str))

    conn.commit()
    conn.close()

    # Process through pipeline on simulation DB
    checkout_classifier.process_checkout_classification_pipeline(db_path)
    checkout_recommender.process_checkout_recommendation_pipeline(db_path)
    checkout_policy_engine.process_checkout_policy_pipeline(db_path)
    checkout_action_executor.process_checkout_execution_pipeline(db_path)

    elapsed_s = round(time.perf_counter() - start_t, 2)

    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.category, c.recommended_action, c.recommendation_reason, c.status,
               pol.policy_decision, pol.policy_reason,
               act.action_taken, act.execution_result, act.business_outcome
        FROM checkouts c
        LEFT JOIN checkout_audit_log pol ON c.id = pol.checkout_id AND pol.event_type = 'POLICY_DECISION'
        LEFT JOIN checkout_audit_log act ON c.id = act.checkout_id AND act.event_type = 'ACTION_EXECUTED'
        WHERE c.id = ?;
    """, (checkout_id,))
    r = cursor.fetchone()
    conn.close()

    return jsonify({
        "status": "success",
        "checkout_id": checkout_id,
        "elapsed_seconds": elapsed_s,
        "category": r["category"] if r else "UNKNOWN_ABANDON",
        "recommended_action": r["recommended_action"] if r else "NONE",
        "recommendation_reason": r["recommendation_reason"] if r else "",
        "policy_decision": r["policy_decision"] if r else "UNKNOWN",
        "policy_reason": r["policy_reason"] if r else "",
        "action_taken": r["action_taken"] if r else "NONE",
        "execution_result": r["execution_result"] if r else "NONE",
        "business_outcome": r["business_outcome"] if r else "NONE",
        "final_status": r["status"] if r else "UNKNOWN"
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
