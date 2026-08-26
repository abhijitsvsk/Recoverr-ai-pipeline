"""
Verification Runner for Checkout Abandonment Loop 2 Foundation.
Executes synthetic dataset generation, schema verification, and 8 automated assertions.
100% separate from Loop 1 payment runners.
"""

import sys
import os
import argparse
import json
import sqlite3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from checkout_db import get_checkout_connection, init_checkout_db, get_checkout_schema_sql
from checkout_generator import (
    generate_checkout_dataset,
    save_checkout_dataset_to_db,
    CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE,
)

DB_PATH = "checkout_recovery.db"


def run_verification(seed: int = 42) -> bool:
    """Run synthetic data generation and execute all 8 assertions."""
    print(f"\n================================================================================")
    print(f"  RUNNING CHECKOUT ABANDONMENT LOOP 2 FOUNDATION VERIFICATION (Seed: {seed})")
    print(f"================================================================================\n")

    # Generate and save dataset
    checkouts, audit_entries, idempotency_records = generate_checkout_dataset(seed)
    save_checkout_dataset_to_db(seed, checkouts, audit_entries, idempotency_records, DB_PATH)

    conn = get_checkout_connection(DB_PATH)
    cursor = conn.cursor()

    print("================================================================================")
    print("1. FULL DATABASE SCHEMA (checkout_recovery.db)")
    print("================================================================================")
    print(get_checkout_schema_sql(DB_PATH))
    print()

    print("================================================================================")
    print("2. 10 SAMPLE GENERATED DB ROWS (Raw checkouts table dicts)")
    print("================================================================================")
    cursor.execute("SELECT * FROM checkouts LIMIT 10;")
    rows = cursor.fetchall()
    sample_rows = [dict(r) for r in rows]
    print(json.dumps(sample_rows, indent=2))
    print()

    print("================================================================================")
    print("3. ASSERTION RESULTS (8 Verification Checks)")
    print("================================================================================")

    all_passed = True
    results = {}

    # Assertion 1: Distribution 45 / 20 / 20 / 15
    cursor.execute("SELECT expected_category, COUNT(*) as cnt FROM checkouts GROUP BY expected_category;")
    dist_rows = cursor.fetchall()
    dist_dict = {r["expected_category"]: r["cnt"] for r in dist_rows}
    expected_dist = {
        "RECENT_ABANDON": 45,
        "STALE_ABANDON": 20,
        "REPEAT_ABANDONER": 20,
        "HIGH_VALUE_ABANDON": 15,
    }
    pass1 = dist_dict == expected_dist
    results["1. Category Distribution (45/20/20/15)"] = (
        pass1,
        f"Actual distribution: {dist_dict}",
    )
    if not pass1:
        all_passed = False

    # Assertion 2: All cart_value_in_paise are integers
    cursor.execute("SELECT id, cart_value_in_paise FROM checkouts;")
    cv_rows = cursor.fetchall()
    all_integers = all(isinstance(r["cart_value_in_paise"], int) and r["cart_value_in_paise"] >= 0 for r in cv_rows)
    results["2. Integer Cart Values (cart_value_in_paise)"] = (
        all_integers,
        f"Total records checked: {len(cv_rows)}, All integer paise: {all_integers}",
    )
    if not all_integers:
        all_passed = False

    # Assertion 3: All records start at status=ABANDONED, category=NULL
    cursor.execute("SELECT COUNT(*) as cnt FROM checkouts WHERE status = 'ABANDONED' AND category IS NULL;")
    abnd_cnt = cursor.fetchone()["cnt"]
    pass3 = abnd_cnt == 100
    results["3. Initial State (status=ABANDONED, category=NULL)"] = (
        pass3,
        f"Count matching initial state: {abnd_cnt}/100",
    )
    if not pass3:
        all_passed = False

    # Assertion 4: expected_category is populated for every record
    cursor.execute("SELECT COUNT(*) as cnt FROM checkouts WHERE expected_category IS NOT NULL AND expected_category != '';")
    exp_cnt = cursor.fetchone()["cnt"]
    pass4 = exp_cnt == 100
    results["4. Ground Truth Populated (expected_category)"] = (
        pass4,
        f"Populated expected_category count: {exp_cnt}/100",
    )
    if not pass4:
        all_passed = False

    # Assertion 5: All REPEAT_ABANDONER records have abandon_count >= 2
    cursor.execute("SELECT id, abandon_count FROM checkouts WHERE expected_category = 'REPEAT_ABANDONER';")
    rep_rows = cursor.fetchall()
    rep_valid = all(r["abandon_count"] >= 2 for r in rep_rows)
    min_rep_count = min(r["abandon_count"] for r in rep_rows) if rep_rows else 0
    results["5. Repeat Abandoner Rule (abandon_count >= 2)"] = (
        rep_valid,
        f"REPEAT_ABANDONER count: {len(rep_rows)}, Min abandon_count: {min_rep_count}, All >= 2: {rep_valid}",
    )
    if not rep_valid:
        all_passed = False

    # Assertion 6: HIGH_VALUE_ABANDON strictly exceeds threshold & NO non-HIGH_VALUE record exceeds threshold
    cursor.execute("SELECT id, expected_category, cart_value_in_paise FROM checkouts WHERE expected_category = 'HIGH_VALUE_ABANDON';")
    hv_rows = cursor.fetchall()
    hv_valid = all(r["cart_value_in_paise"] > CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE for r in hv_rows)

    cursor.execute("SELECT id, expected_category, cart_value_in_paise FROM checkouts WHERE expected_category != 'HIGH_VALUE_ABANDON';")
    non_hv_rows = cursor.fetchall()
    non_hv_valid = all(r["cart_value_in_paise"] <= CHECKOUT_HIGH_VALUE_THRESHOLD_PAISE for r in non_hv_rows)

    pass6 = hv_valid and non_hv_valid
    results["6. Mutual Exclusivity Threshold (HV > 10,000 INR & non-HV <= 10,000 INR)"] = (
        pass6,
        f"HV count > thresh: {len(hv_rows)} ({hv_valid}), Non-HV count <= thresh: {len(non_hv_rows)} ({non_hv_valid})",
    )
    if not pass6:
        all_passed = False

    # Assertion 7: checkout_audit_log append-only triggers reject UPDATE and DELETE
    trigger_pass = False
    try:
        # Attempt update
        conn.execute("UPDATE checkout_audit_log SET category = 'RECENT_ABANDON' WHERE id = 'aud_abnd_42_001';")
    except sqlite3.IntegrityError:
        try:
            # Attempt delete
            conn.execute("DELETE FROM checkout_audit_log WHERE id = 'aud_abnd_42_001';")
        except sqlite3.IntegrityError:
            trigger_pass = True

    results["7. Audit Log Append-Only Triggers Reject UPDATE/DELETE"] = (
        trigger_pass,
        f"UPDATE and DELETE attempts correctly raised sqlite3.IntegrityError: {trigger_pass}",
    )
    if not trigger_pass:
        all_passed = False

    # Assertion 8: checkout_idempotency unique constraint on event_id is enforced
    idempotency_pass = False
    try:
        conn.execute(
            "INSERT INTO checkout_idempotency (event_id, checkout_id, processed_at) VALUES ('evt_abnd_42_001', 'chk_42_001', '2026-08-22T12:00:00+00:00');"
        )
    except sqlite3.IntegrityError:
        idempotency_pass = True

    results["8. Idempotency Unique Constraint on event_id"] = (
        idempotency_pass,
        f"Duplicate event_id insertion correctly raised sqlite3.IntegrityError: {idempotency_pass}",
    )
    if not idempotency_pass:
        all_passed = False

    conn.close()

    # Display assertion summary
    for title, (passed, details) in results.items():
        status_str = "[PASS]" if passed else "[FAIL]"
        print(f"  {status_str} {title}")
        print(f"          └─ {details}")

    print("\n================================================================================")
    if all_passed:
        print("[SUCCESS] All 8 Loop 2 checkout foundation assertions PASSED!")
    else:
        print("[FAILURE] One or more assertions FAILED.")
    print("================================================================================\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Checkout Abandonment Loop 2 Foundation Verification Runner")
    parser.add_argument("--seed", type=int, default=42, help="Fixed random seed for generation (default: 42)")
    args = parser.parse_args()

    success = run_verification(seed=args.seed)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
