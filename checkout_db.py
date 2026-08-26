"""
Database Module for Checkout Abandonment Loop 2 Foundation.
Manages checkout_recovery.db SQLite schema, triggers, and data access.
100% separate from Loop 1 recover_ai.db database.
"""

import os
import sqlite3
from typing import List, Dict, Any, Optional

CHECKOUT_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS checkouts (
    id TEXT PRIMARY KEY,
    cart_value_in_paise INTEGER NOT NULL CHECK (cart_value_in_paise >= 0),
    customer_abandon_reason TEXT NOT NULL,
    expected_category TEXT NOT NULL CHECK (expected_category IN (
        'RECENT_ABANDON', 'STALE_ABANDON', 'REPEAT_ABANDONER', 'HIGH_VALUE_ABANDON', 'UNKNOWN_ABANDON'
    )),
    category TEXT CHECK (category IS NULL OR category IN (
        'RECENT_ABANDON', 'STALE_ABANDON', 'REPEAT_ABANDONER', 'HIGH_VALUE_ABANDON', 'UNKNOWN_ABANDON'
    )),
    status TEXT NOT NULL CHECK (status IN (
        'ABANDONED', 'CLASSIFIED', 'RECOMMENDED', 'APPROVED', 'BLOCKED', 
        'EXECUTING', 'SUCCEEDED', 'FAILED_EXECUTION', 'ESCALATED', 'STOPPED'
    )),
    abandon_count INTEGER NOT NULL CHECK (abandon_count >= 1),
    abandoned_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    recommended_action TEXT CHECK (recommended_action IS NULL OR recommended_action IN (
        'SEND_CART_REMINDER', 'SEND_DISCOUNT_NUDGE', 'ESCALATE', 'STOP'
    )),
    recommendation_reason TEXT,
    policy_decision TEXT CHECK (policy_decision IS NULL OR policy_decision IN ('APPROVED', 'BLOCKED')),
    policy_reason TEXT,
    cart_recovery_confirmed INTEGER DEFAULT 0 CHECK (cart_recovery_confirmed IN (0, 1)),
    expected_recovery_value_paise REAL DEFAULT 0.0,
    recommended_expected_value_paise REAL DEFAULT 0.0
);


CREATE TABLE IF NOT EXISTS checkout_audit_log (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    checkout_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    category TEXT CHECK (category IS NULL OR category IN (
        'RECENT_ABANDON', 'STALE_ABANDON', 'REPEAT_ABANDONER', 'HIGH_VALUE_ABANDON', 'UNKNOWN_ABANDON'
    )),
    recommended_action TEXT CHECK (recommended_action IS NULL OR recommended_action IN (
        'SEND_CART_REMINDER', 'SEND_DISCOUNT_NUDGE', 'ESCALATE', 'STOP'
    )),
    policy_decision TEXT,
    policy_reason TEXT,
    action_taken TEXT,
    execution_result TEXT,
    business_outcome TEXT,
    cart_value_in_paise INTEGER NOT NULL CHECK (cart_value_in_paise >= 0),
    FOREIGN KEY (checkout_id) REFERENCES checkouts(id)
);

CREATE TRIGGER IF NOT EXISTS checkout_audit_log_no_update
BEFORE UPDATE ON checkout_audit_log
BEGIN
    SELECT RAISE(FAIL, 'checkout_audit_log is append-only: updates forbidden');
END;

CREATE TRIGGER IF NOT EXISTS checkout_audit_log_no_delete
BEFORE DELETE ON checkout_audit_log
BEGIN
    SELECT RAISE(FAIL, 'checkout_audit_log is append-only: deletes forbidden');
END;

CREATE TABLE IF NOT EXISTS checkout_idempotency (
    event_id TEXT PRIMARY KEY,
    checkout_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    FOREIGN KEY (checkout_id) REFERENCES checkouts(id)
);

CREATE TABLE IF NOT EXISTS checkout_dataset_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed INTEGER NOT NULL,
    record_count INTEGER NOT NULL,
    generated_at TEXT NOT NULL
);
"""


def get_checkout_connection(db_path: str = "checkout_recovery.db") -> sqlite3.Connection:
    """Connect to SQLite database for Loop 2 checkout recovery."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_checkout_db(db_path: str = "checkout_recovery.db") -> None:
    """Initialize Loop 2 database schema, apply migrations, and append-only triggers."""
    conn = get_checkout_connection(db_path)
    with conn:
        conn.executescript(CHECKOUT_SCHEMA_SQL)
        # Check if recommended_action column exists in checkouts table
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(checkouts);")
        columns = [row["name"] for row in cursor.fetchall()]
        if "recommended_action" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN recommended_action TEXT CHECK (recommended_action IS NULL OR recommended_action IN ('SEND_CART_REMINDER', 'SEND_DISCOUNT_NUDGE', 'ESCALATE', 'STOP'));")
        if "recommendation_reason" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN recommendation_reason TEXT;")
        if "policy_decision" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN policy_decision TEXT CHECK (policy_decision IS NULL OR policy_decision IN ('APPROVED', 'BLOCKED'));")
        if "policy_reason" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN policy_reason TEXT;")
        if "cart_recovery_confirmed" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN cart_recovery_confirmed INTEGER DEFAULT 0 CHECK (cart_recovery_confirmed IN (0, 1));")
        if "expected_recovery_value_paise" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN expected_recovery_value_paise REAL DEFAULT 0.0;")
        if "recommended_expected_value_paise" not in columns:
            cursor.execute("ALTER TABLE checkouts ADD COLUMN recommended_expected_value_paise REAL DEFAULT 0.0;")
    conn.close()



def get_checkout_schema_sql(db_path: str = "checkout_recovery.db") -> str:
    """Retrieve full schema text from sqlite_master for checkout_recovery.db."""
    conn = get_checkout_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table', 'trigger');")
    rows = cursor.fetchall()
    conn.close()
    return "\n\n".join(row["sql"] for row in rows)


def create_checkout_snapshot(
    db_path: str = "checkout_recovery.db",
    snapshot_path: str = "checkout_recovery_verified_snapshot.db",
) -> None:
    """Save verified Loop 2 database state as a snapshot backup file."""
    import shutil
    shutil.copyfile(db_path, snapshot_path)


def restore_checkout_snapshot(
    snapshot_path: str = "checkout_recovery_verified_snapshot.db",
    db_path: str = "checkout_recovery.db",
) -> None:
    """Instantly restore Loop 2 database from verified snapshot backup file (<10ms)."""
    import shutil
    if not os.path.exists(snapshot_path):
        raise FileNotFoundError(f"Snapshot file '{snapshot_path}' does not exist.")
    shutil.copyfile(snapshot_path, db_path)
