"""
Synthetic Data Generator for Loop 3: Duplicate Charge Detection & Auto-Refund.
Generates 100 reproducible duplicate charge candidate records (seed=42).
Includes deliberate false-positive cases (UNRELATED) to prove non-problem recognition.
"""

import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Dict, Any

from dup_models import DupCategory, DupStatus, DupCharge, DupAuditLogEntry, DupIdempotencyRecord
from dup_db import get_dup_connection, init_dup_db

DUP_DISTRIBUTION = [
    (DupCategory.EXACT_DUPLICATE.value, 35),
    (DupCategory.LIKELY_DUPLICATE.value, 25),
    (DupCategory.SUSPECTED_DUPLICATE.value, 15),
    (DupCategory.UNRELATED.value, 25),  # 25 deliberate false-positives
]


def generate_dup_dataset(
    seed: int = 42,
) -> Tuple[List[DupCharge], List[DupAuditLogEntry], List[DupIdempotencyRecord]]:
    rng = random.Random(seed)

    categories = []
    for cat_name, count in DUP_DISTRIBUTION:
        categories.extend([cat_name] * count)

    rng.shuffle(categories)

    base_time = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)
    charges: List[DupCharge] = []
    audit_entries: List[DupAuditLogEntry] = []
    idempotency_records: List[DupIdempotencyRecord] = []

    for i, gt_cat in enumerate(categories, start=1):
        cid = f"chg_42_{i:03d}"
        cust_id = f"cust_{(i % 30) + 1:03d}"
        created_dt = base_time + timedelta(seconds=i * 45)
        created_str = created_dt.isoformat()

        # Flag repeat pattern for 5 records to test REPEATED_FAILURE override equivalent
        prior_dups = 2 if i in [5, 18, 42, 67, 88] else rng.choice([0, 0, 0, 1])

        if gt_cat == DupCategory.EXACT_DUPLICATE.value:
            order_id = f"ord_dup_{(i % 20) + 1:03d}"
            card_id = f"card_{(i % 15) + 1:03d}"
            # Mix amounts: 5 high-value (>₹40,000) for policy hold testing
            if i in [10, 25, 35, 50, 75]:
                amount = rng.choice([4500000, 5500000, 8000000])  # ₹45k, ₹55k, ₹80k
            else:
                amount = rng.choice([49900, 149900, 299900, 899000, 1500000])  # ₹499 - ₹15,000
            time_delta = rng.randint(5, 1800)  # <= 60 mins (3600s)
            purchase_type = "accidental_double_click"

        elif gt_cat == DupCategory.LIKELY_DUPLICATE.value:
            order_id_1 = f"ord_a_{i:03d}"
            card_id = f"card_{(i % 15) + 1:03d}"
            amount = rng.choice([99900, 199900, 349900, 1200000])  # ₹999 - ₹12,000
            time_delta = rng.randint(2, 28)  # <= 30s
            order_id = f"ord_b_{i:03d}"  # Different order_id
            purchase_type = "rapid_recheckout"

        elif gt_cat == DupCategory.SUSPECTED_DUPLICATE.value:
            order_id = f"ord_c_{i:03d}"
            card_id = f"card_diff_{i:03d}"  # Different card
            amount = rng.choice([49900, 149900, 250000])
            time_delta = rng.randint(35, 280)  # <= 300s (5 mins)
            purchase_type = "multi_instrument_retry"

        else:  # UNRELATED — Deliberate False Positives
            order_id = f"ord_legit_{i:03d}"
            card_id = f"card_user_{i:03d}"
            amount = 49900  # e.g. ₹499 in-game microtransaction
            time_delta = rng.randint(3, 10)  # 3s apart, but distinct orders/items
            purchase_type = "in_game_microtransaction_legit"

        charge = DupCharge(
            id=cid,
            customer_id=cust_id,
            order_id=order_id,
            card_id=card_id,
            amount_in_paise=amount,
            time_delta_seconds=time_delta,
            prior_duplicate_count=prior_dups,
            purchase_type=purchase_type,
            ground_truth_category=gt_cat,
            status=DupStatus.INGESTED.value,
            created_at=created_str,
            updated_at=created_str,
        )
        charges.append(charge)

        evt_id = f"evt_dup_ingest_{cid}"
        audit_entry = DupAuditLogEntry(
            id=f"aud_ingest_{cid}",
            event_id=evt_id,
            event_type="CHARGE_INGESTED",
            charge_id=cid,
            timestamp=created_str,
            amount_in_paise=amount,
            category=None,
            recommended_action=None,
            policy_decision=None,
            policy_reason=None,
            action_taken="INGEST",
            execution_result="ingested",
            business_outcome="pending_classification",
        )
        audit_entries.append(audit_entry)

        idem = DupIdempotencyRecord(
            event_id=evt_id,
            charge_id=cid,
            processed_at=created_str,
        )
        idempotency_records.append(idem)

    return charges, audit_entries, idempotency_records


def seed_dup_database(db_path: str = "duplicate_charge.db", seed: int = 42) -> None:
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    init_dup_db(db_path)
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    charges, audit_entries, idem_records = generate_dup_dataset(seed=seed)

    for c in charges:
        cursor.execute(
            """
            INSERT INTO duplicate_charges (
                id, customer_id, order_id, card_id, amount_in_paise,
                time_delta_seconds, prior_duplicate_count, purchase_type,
                ground_truth_category, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                c.id, c.customer_id, c.order_id, c.card_id, c.amount_in_paise,
                c.time_delta_seconds, c.prior_duplicate_count, c.purchase_type,
                c.ground_truth_category, c.status, c.created_at, c.updated_at,
            ),
        )

    for a in audit_entries:
        cursor.execute(
            """
            INSERT INTO dup_audit_log (
                id, event_id, event_type, charge_id, timestamp,
                amount_in_paise, category, recommended_action, policy_decision,
                policy_reason, action_taken, execution_result, business_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                a.id, a.event_id, a.event_type, a.charge_id, a.timestamp,
                a.amount_in_paise, a.category, a.recommended_action, a.policy_decision,
                a.policy_reason, a.action_taken, a.execution_result, a.business_outcome,
            ),
        )

    for r in idem_records:
        cursor.execute(
            """
            INSERT INTO dup_idempotency (event_id, charge_id, processed_at)
            VALUES (?, ?, ?);
            """,
            (r.event_id, r.charge_id, r.processed_at),
        )

    conn.commit()
    conn.close()
