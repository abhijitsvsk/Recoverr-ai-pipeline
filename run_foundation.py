"""
Runner and Verification Suite for RecoverAI Payment Recovery Foundation.

Executes database schema setup, synthetic dataset generation, schema and sample output,
and full verification of all constraints, distribution, idempotency, audit triggers, and reproducibility.
"""

import argparse
import json
import random
import sqlite3
import sys
from typing import Dict, Any, List

from db import init_db, get_connection, get_schema_sql
from generator import generate_dataset, save_dataset_to_db, DISTRIBUTION
from models import Category, PaymentStatus


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI Payment Recovery Foundation Runner")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Integer seed for reproducible synthetic data generation",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def verify_foundation(seed: int, db_path: str) -> Dict[str, Any]:
    """
    Execute strict verification assertions against database schema, records,
    distribution, idempotency, append-only triggers, and canonical reproducibility.
    """
    results = {}
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Ground Truth Category Breakdown Check
    cursor.execute(
        "SELECT ground_truth_category, COUNT(*) as count FROM payments GROUP BY ground_truth_category;"
    )
    counts = {row["ground_truth_category"]: row["count"] for row in cursor.fetchall()}
    expected_counts = {"TEMPORARY": 40, "PERMANENT": 25, "REPEATED_FAILURE": 20, "UNKNOWN": 15}

    results["category_distribution"] = counts
    assert counts == expected_counts, f"Category breakdown mismatch! Got {counts}, expected {expected_counts}"

    # 2. Integer Paise Validation
    cursor.execute("SELECT id, amount_in_paise FROM payments;")
    payment_amounts = cursor.fetchall()
    assert len(payment_amounts) == 100, f"Expected 100 payments, got {len(payment_amounts)}"
    for p in payment_amounts:
        amt = p["amount_in_paise"]
        assert isinstance(amt, int), f"Amount {amt} for payment {p['id']} is not an integer"
        assert amt >= 0, f"Amount {amt} for payment {p['id']} is negative"
    results["integer_paise_verified"] = True

    # 3. Status and Category Initialization Check
    cursor.execute("SELECT DISTINCT status FROM payments;")
    statuses = [r["status"] for r in cursor.fetchall()]
    assert statuses == ["FAILED"], f"Expected all payments to have status 'FAILED', got {statuses}"

    cursor.execute("SELECT COUNT(*) as count FROM payments WHERE category IS NOT NULL;")
    non_null_category_count = cursor.fetchone()["count"]
    assert non_null_category_count == 0, f"Expected category IS NULL for all initial records, got {non_null_category_count}"
    results["initial_status_and_null_category_verified"] = True

    # 4. Ground Truth Category Population & Isolation Check
    cursor.execute("SELECT COUNT(*) as count FROM payments WHERE ground_truth_category IS NULL;")
    null_gt_count = cursor.fetchone()["count"]
    assert null_gt_count == 0, "ground_truth_category must be populated for all records"
    results["ground_truth_populated_verified"] = True

    # 5. Repeated Failure Attempt Count Check (attempt_count >= 3 strictly reclassifies to REPEATED_FAILURE)
    cursor.execute(
        "SELECT attempt_count FROM payments WHERE ground_truth_category = 'REPEATED_FAILURE';"
    )
    rf_attempts = [r["attempt_count"] for r in cursor.fetchall()]
    assert len(rf_attempts) == 20, f"Expected 20 REPEATED_FAILURE records, got {len(rf_attempts)}"
    assert all(att >= 3 for att in rf_attempts), f"REPEATED_FAILURE must have attempt_count >= 3, got {rf_attempts}"

    cursor.execute(
        "SELECT COUNT(*) as count FROM payments WHERE attempt_count >= 3 AND ground_truth_category != 'REPEATED_FAILURE';"
    )
    invalid_att_count = cursor.fetchone()["count"]
    assert invalid_att_count == 0, f"Found {invalid_att_count} records with attempt_count >= 3 that were not marked REPEATED_FAILURE!"

    cursor.execute(
        "SELECT COUNT(*) as count FROM payments WHERE attempt_count < 3 AND ground_truth_category = 'REPEATED_FAILURE';"
    )
    invalid_rf_count = cursor.fetchone()["count"]
    assert invalid_rf_count == 0, f"Found {invalid_rf_count} REPEATED_FAILURE records with attempt_count < 3!"

    results["repeated_failure_attempts_verified"] = True

    # 6. Idempotency Constraint Verification (Duplicate event_id rejection)
    cursor.execute("SELECT event_id, payment_id FROM idempotency LIMIT 1;")
    sample_idem = cursor.fetchone()
    duplicate_event_id = sample_idem["event_id"]
    duplicate_payment_id = sample_idem["payment_id"]

    idempotency_rejected = False
    try:
        cursor.execute(
            "INSERT INTO idempotency (event_id, payment_id, processed_at) VALUES (?, ?, ?);",
            (duplicate_event_id, duplicate_payment_id, "2026-08-22T12:00:00Z"),
        )
    except sqlite3.IntegrityError:
        idempotency_rejected = True

    assert idempotency_rejected, "Idempotency table failed to reject duplicate event_id!"
    results["idempotency_unique_constraint_verified"] = True

    # 7. Audit Log Append-Only Triggers Verification (UPDATE & DELETE rejection)
    cursor.execute("SELECT id FROM audit_log LIMIT 1;")
    sample_audit = cursor.fetchone()
    audit_id = sample_audit["id"]

    update_rejected = False
    try:
        cursor.execute("UPDATE audit_log SET event_type = 'MODIFIED' WHERE id = ?;", (audit_id,))
    except sqlite3.IntegrityError as e:
        if "append-only: updates forbidden" in str(e):
            update_rejected = True

    assert update_rejected, "Audit log trigger failed to reject UPDATE operation!"

    delete_rejected = False
    try:
        cursor.execute("DELETE FROM audit_log WHERE id = ?;", (audit_id,))
    except sqlite3.IntegrityError as e:
        if "append-only: deletes forbidden" in str(e):
            delete_rejected = True

    assert delete_rejected, "Audit log trigger failed to reject DELETE operation!"

    results["audit_append_only_triggers_verified"] = True

    # 8. Canonical Reproducibility Verification
    payments_run1, audit_run1, idem_run1 = generate_dataset(seed)
    payments_run2, audit_run2, idem_run2 = generate_dataset(seed)

    canonical_1 = json.dumps([p.__dict__ for p in sorted(payments_run1, key=lambda x: x.id)], sort_keys=True)
    canonical_2 = json.dumps([p.__dict__ for p in sorted(payments_run2, key=lambda x: x.id)], sort_keys=True)

    assert canonical_1 == canonical_2, "Canonical reproducibility check failed! Rerunning with same seed yielded different records."
    results["canonical_reproducibility_verified"] = True

    conn.close()
    return results


def main():
    args = parse_args()

    # Determine seed
    if args.seed is None:
        seed = random.randint(100000, 999999)
        print(f"No seed supplied. Generated random integer seed: {seed}")
    else:
        seed = args.seed
        print(f"Using supplied integer seed: {seed}")

    # 1. Initialize Database Schema
    init_db(args.db_path)

    # 2. Generate Dataset and Save to DB
    payments, audit_entries, idempotency_records = generate_dataset(seed)
    save_dataset_to_db(seed, payments, audit_entries, idempotency_records, args.db_path)

    # 3. Print Final SQLite Schema
    schema_sql = get_schema_sql(args.db_path)
    print("\n" + "=" * 80)
    print("FINAL DATABASE SCHEMA (SQLite)")
    print("=" * 80)
    print(schema_sql)

    # 4. Print Sample Generated Records
    print("\n" + "=" * 80)
    print("SAMPLE GENERATED RECORDS (First 5 Payments)")
    print("=" * 80)
    sample_records = [p.__dict__ for p in payments[:5]]
    print(json.dumps(sample_records, indent=2))

    # 5. Run Verification Assertions
    print("\n" + "=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    verification_results = verify_foundation(seed, args.db_path)
    for k, v in verification_results.items():
        print(f"  [PASSED] {k}: {v}")

    print("\nFoundation build & verification completed successfully!")


if __name__ == "__main__":
    main()
