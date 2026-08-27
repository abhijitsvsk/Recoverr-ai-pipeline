"""
Step runner for Loop 3 Foundation: Data Generation & Database Initialization.
"""

from dup_db import init_dup_db, get_dup_connection
from dup_generator import seed_dup_database

def run():
    print("=== LOOP 3 FOUNDATION: INITIALIZING DUPLICATE CHARGE DATABASE ===")
    seed_dup_database("duplicate_charge.db", seed=42)
    conn = get_dup_connection("duplicate_charge.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM duplicate_charges;")
    cnt = cursor.fetchone()[0]
    print(f"Initialized duplicate_charge.db with {cnt} synthetic records.")

    cursor.execute("SELECT ground_truth_category, COUNT(*) FROM duplicate_charges GROUP BY ground_truth_category;")
    print("Ground Truth Distribution:", dict(cursor.fetchall()))
    conn.close()

if __name__ == "__main__":
    run()
