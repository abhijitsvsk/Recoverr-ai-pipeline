"""
Database initialization and connection management for Loop 3: Duplicate Charge Detection.
100% separate from Loop 1 (recover_ai.db) and Loop 2 (checkout_recovery.db).
Uses SQLite triggers for application-enforced append-only audit log protection.
"""

import os
import sqlite3
from typing import Optional

DEFAULT_DUP_DB_PATH = "duplicate_charge.db"
SNAPSHOT_DUP_DB_PATH = "duplicate_charge_verified_snapshot.db"
LIVE_TEST_DUP_DB_PATH = "duplicate_charge_live_test.db"


def get_dup_connection(db_path: str = DEFAULT_DUP_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_dup_db(db_path: str = DEFAULT_DUP_DB_PATH) -> None:
    conn = get_dup_connection(db_path)
    cursor = conn.cursor()

    # 1. Main duplicate charges table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS duplicate_charges (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            amount_in_paise INTEGER NOT NULL,
            time_delta_seconds INTEGER NOT NULL,
            prior_duplicate_count INTEGER NOT NULL DEFAULT 0,
            purchase_type TEXT NOT NULL DEFAULT 'standard',
            ground_truth_category TEXT NOT NULL,
            category TEXT CHECK(category IN ('EXACT_DUPLICATE', 'LIKELY_DUPLICATE', 'SUSPECTED_DUPLICATE', 'UNRELATED') OR category IS NULL),
            status TEXT NOT NULL CHECK(status IN ('INGESTED', 'CLASSIFIED', 'RECOMMENDED', 'APPROVED', 'BLOCKED', 'EXECUTING', 'SUCCEEDED', 'FAILED_EXECUTION', 'ESCALATED', 'NO_ACTION_TAKEN')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            recommended_action TEXT,
            recommendation_reason TEXT,
            policy_decision TEXT,
            policy_reason TEXT,
            action_taken TEXT,
            execution_result TEXT,
            business_outcome TEXT
        );
    """)

    # 2. Application-enforced append-only audit log table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dup_audit_log (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            charge_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            category TEXT,
            recommended_action TEXT,
            policy_decision TEXT,
            policy_reason TEXT,
            action_taken TEXT,
            execution_result TEXT,
            business_outcome TEXT,
            amount_in_paise INTEGER NOT NULL
        );
    """)

    # 3. Idempotency tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dup_idempotency (
            event_id TEXT PRIMARY KEY,
            charge_id TEXT NOT NULL,
            processed_at TEXT NOT NULL
        );
    """)

    # 4. Triggers protecting dup_audit_log against in-app updates and deletes
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS dup_audit_log_no_update
        BEFORE UPDATE ON dup_audit_log
        BEGIN
            SELECT RAISE(FAIL, 'UPDATE operation forbidden on append-only table dup_audit_log');
        END;
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS dup_audit_log_no_delete
        BEFORE DELETE ON dup_audit_log
        BEGIN
            SELECT RAISE(FAIL, 'DELETE operation forbidden on append-only table dup_audit_log');
        END;
    """)

    conn.commit()
    conn.close()
