"""
Runner & Verification Suite for RecoverAI Failure Classifier.
Runs classification pipeline across generated dataset and validates output against ground_truth_category.
"""

import argparse
import json
import sqlite3
from typing import Dict, Any, List

from db import init_db, get_connection
from generator import generate_dataset, save_dataset_to_db
from classifier import process_classification_pipeline, classify_failure


def parse_args():
    parser = argparse.ArgumentParser(description="RecoverAI Failure Classifier Runner")
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Integer seed for dataset generation (default: 42)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="recover_ai.db",
        help="Path to SQLite database file",
    )
    return parser.parse_args()


def run_and_validate_classifier(db_path: str) -> Dict[str, Any]:
    """Execute classification pipeline and validate accuracy against ground truth."""
    # 1. Run Classification Pipeline
    classified_count = process_classification_pipeline(db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 2. Fetch all classified payments and compare category with ground_truth_category
    cursor.execute(
        """
        SELECT id, failure_reason, attempt_count, ground_truth_category, category, status 
        FROM payments 
        ORDER BY id;
        """
    )
    payments = cursor.fetchall()

    mismatches = []
    matches = 0

    for p in payments:
        gt_cat = p["ground_truth_category"]
        assigned_cat = p["category"]

        if assigned_cat == gt_cat:
            matches += 1
        else:
            mismatches.append(
                {
                    "payment_id": p["id"],
                    "failure_reason": p["failure_reason"],
                    "attempt_count": p["attempt_count"],
                    "ground_truth_category": gt_cat,
                    "category_assigned": assigned_cat,
                }
            )

    accuracy_pct = (matches / len(payments)) * 100.0 if payments else 0.0

    # 3. Verify CLASSIFIED audit log rows exist for every record
    cursor.execute(
        """
        SELECT COUNT(*) as count 
        FROM audit_log 
        WHERE event_type = 'CLASSIFIED';
        """
    )
    audit_classified_count = cursor.fetchone()["count"]

    # 4. Fetch 5 sample classified payments
    cursor.execute(
        """
        SELECT id, failure_reason, attempt_count, category, status 
        FROM payments 
        LIMIT 5;
        """
    )
    sample_payments = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "total_payments": len(payments),
        "classified_count": classified_count,
        "matches": matches,
        "mismatches": mismatches,
        "accuracy_pct": accuracy_pct,
        "audit_classified_count": audit_classified_count,
        "sample_payments": sample_payments,
    }


def main():
    args = parse_args()

    # Ensure dataset is generated afresh for reproducibility
    init_db(args.db_path)
    payments, audit_entries, idempotency_records = generate_dataset(args.seed)
    save_dataset_to_db(args.seed, payments, audit_entries, idempotency_records, args.db_path)

    print("\n" + "=" * 80)
    print(f"RUNNING FAILURE CLASSIFIER (Dataset Seed: {args.seed})")
    print("=" * 80)

    res = run_and_validate_classifier(args.db_path)

    print(f"\nTotal Records Processed : {res['classified_count']} / {res['total_payments']}")
    print(f"Classification Accuracy : {res['accuracy_pct']:.2f}% ({res['matches']}/{res['total_payments']} matching)")

    print("\n" + "=" * 80)
    print("MISMATCH BREAKDOWN")
    print("=" * 80)
    if res["mismatches"]:
        print(f"Found {len(res['mismatches'])} mismatches:")
        print(json.dumps(res["mismatches"], indent=2))
    else:
        print("0 Mismatches found! 100% agreement between Classifier and Ground Truth labels.")

    print("\n" + "=" * 80)
    print("SAMPLE CLASSIFIED PAYMENTS (First 5)")
    print("=" * 80)
    print(json.dumps(res["sample_payments"], indent=2))

    print("\n" + "=" * 80)
    print("AUDIT LOG VERIFICATION")
    print("=" * 80)
    print(f"Total CLASSIFIED audit log rows created: {res['audit_classified_count']}")
    assert res["audit_classified_count"] == res["total_payments"], "Audit log count mismatch!"
    print("Verified: Every classified payment has a corresponding 'CLASSIFIED' audit_log entry.")

    print("\nFailure Classifier run and validation complete!")


if __name__ == "__main__":
    main()
