"""
Database module for RecoverAI Payment Recovery Agent Foundation.
Provides SQLite initialization, table creation, triggers, and data access methods.
"""

import os
import shutil
import sqlite3
from typing import List, Dict, Any, Optional

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    amount_in_paise INTEGER NOT NULL CHECK (amount_in_paise >= 0),
    failure_reason TEXT NOT NULL,
    ground_truth_category TEXT NOT NULL CHECK (ground_truth_category IN ('TEMPORARY', 'PERMANENT', 'REPEATED_FAILURE', 'UNKNOWN')),
    category TEXT CHECK (category IS NULL OR category IN ('TEMPORARY', 'PERMANENT', 'REPEATED_FAILURE', 'UNKNOWN')),
    status TEXT NOT NULL CHECK (status IN (
        'FAILED', 'CLASSIFIED', 'RECOMMENDED', 'APPROVED', 'BLOCKED', 
        'EXECUTING', 'SUCCEEDED', 'FAILED_EXECUTION', 'ESCALATED', 'STOPPED'
    )),
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
    last_attempt_at TEXT NOT NULL,
    recommended_action TEXT CHECK (recommended_action IS NULL OR recommended_action IN ('RETRY', 'SEND_RECOVERY_LINK', 'ESCALATE', 'STOP')),
    recommendation_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expected_recovery_value_paise REAL DEFAULT 0.0,
    recommended_expected_value_paise REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payment_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    timestamp TEXT NOT NULL,
    category TEXT CHECK (category IS NULL OR category IN ('TEMPORARY', 'PERMANENT', 'REPEATED_FAILURE', 'UNKNOWN')),
    recommended_action TEXT,
    policy_decision TEXT,
    policy_reason TEXT,
    action_taken TEXT,
    execution_result TEXT,
    business_outcome TEXT,
    amount_in_paise INTEGER NOT NULL CHECK (amount_in_paise >= 0),
    FOREIGN KEY (payment_id) REFERENCES payments(id)
);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(FAIL, 'audit_log is append-only: updates forbidden');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(FAIL, 'audit_log is append-only: deletes forbidden');
END;

CREATE TABLE IF NOT EXISTS idempotency (
    event_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    FOREIGN KEY (payment_id) REFERENCES payments(id)
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed INTEGER NOT NULL,
    record_count INTEGER NOT NULL,
    generated_at TEXT NOT NULL
);
"""


def get_connection(db_path: str = "recover_ai.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = "recover_ai.db") -> None:
    """Initialize database tables, apply schema migrations, and setup triggers."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript(SCHEMA_SQL)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(payments);")
        columns = [row["name"] for row in cursor.fetchall()]
        if "expected_recovery_value_paise" not in columns:
            cursor.execute("ALTER TABLE payments ADD COLUMN expected_recovery_value_paise REAL DEFAULT 0.0;")
        if "recommended_expected_value_paise" not in columns:
            cursor.execute("ALTER TABLE payments ADD COLUMN recommended_expected_value_paise REAL DEFAULT 0.0;")
    conn.close()


def get_schema_sql(db_path: str = "recover_ai.db") -> str:
    """Retrieve full schema text from sqlite_master."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table', 'trigger');")
    rows = cursor.fetchall()
    conn.close()
    return "\n\n".join(row["sql"] for row in rows)


def create_snapshot(
    db_path: str = "recover_ai.db",
    snapshot_path: str = "recover_ai_verified_snapshot.db",
) -> None:
    """Save verified database state as a snapshot backup file."""
    import shutil
    shutil.copyfile(db_path, snapshot_path)


def restore_snapshot(
    snapshot_path: str = "recover_ai_verified_snapshot.db",
    db_path: str = "recover_ai.db",
) -> None:
    """Instantly restore database from verified snapshot backup file (<10ms)."""
    import shutil
    if not os.path.exists(snapshot_path):
        raise FileNotFoundError(f"Snapshot file '{snapshot_path}' does not exist. Run verification reset first.")
    shutil.copyfile(snapshot_path, db_path)

