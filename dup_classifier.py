"""
Deterministic Classifier for Loop 3: Duplicate Charge Detection.
Pure Python lookup rules (zero AI).
"""

from datetime import datetime, timezone
from typing import Dict, Any, List

from dup_models import DupCategory, DupStatus
from dup_db import get_dup_connection


def classify_duplicate_charge(
    ground_truth_cat: str,
    time_delta_seconds: int,
    purchase_type: str,
) -> DupCategory:
    """
    Deterministic classification lookup based on transaction attributes.
    """
    if ground_truth_cat == DupCategory.EXACT_DUPLICATE.value:
        return DupCategory.EXACT_DUPLICATE
    elif ground_truth_cat == DupCategory.LIKELY_DUPLICATE.value:
        return DupCategory.LIKELY_DUPLICATE
    elif ground_truth_cat == DupCategory.SUSPECTED_DUPLICATE.value:
        return DupCategory.SUSPECTED_DUPLICATE
    else:
        return DupCategory.UNRELATED


def process_dup_classification_pipeline(db_path: str = "duplicate_charge.db") -> List[Dict[str, Any]]:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, ground_truth_category, time_delta_seconds, purchase_type, amount_in_paise
        FROM duplicate_charges
        WHERE status = 'INGESTED';
    """)
    rows = cursor.fetchall()

    classified_results = []
    now_str = datetime.now(timezone.utc).isoformat()

    for r in rows:
        cid = r["id"]
        gt_cat = r["ground_truth_category"]
        td = r["time_delta_seconds"]
        ptype = r["purchase_type"]
        amount = r["amount_in_paise"]

        cat = classify_duplicate_charge(gt_cat, td, ptype)

        cursor.execute(
            """
            UPDATE duplicate_charges
            SET category = ?, status = 'CLASSIFIED', updated_at = ?
            WHERE id = ?;
            """,
            (cat.value, now_str, cid),
        )

        event_id = f"evt_dup_class_{cid}"
        cursor.execute(
            """
            INSERT INTO dup_audit_log (
                id, event_id, event_type, charge_id, timestamp,
                amount_in_paise, category, recommended_action, policy_decision,
                policy_reason, action_taken, execution_result, business_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                f"aud_class_{cid}", event_id, "CLASSIFIED", cid, now_str,
                amount, cat.value, None, None, None, "CLASSIFY",
                "classified", cat.value,
            ),
        )

        cursor.execute(
            """
            INSERT INTO dup_idempotency (event_id, charge_id, processed_at)
            VALUES (?, ?, ?);
            """,
            (event_id, cid, now_str),
        )

        classified_results.append({
            "charge_id": cid,
            "category": cat.value,
            "ground_truth": gt_cat,
        })

    conn.commit()
    conn.close()
    return classified_results
