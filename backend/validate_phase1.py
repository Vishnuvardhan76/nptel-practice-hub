"""
Phase 1 Validation Script for NPTEL Practice Hub
Validates tables, columns, foreign keys, uniqueness constraints, re-initialization,
database path resolution, and data preservation.
"""

import sys
from pathlib import Path

# Ensure backend directory is in sys.path regardless of CWD
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import sqlite3
from database import (
    get_db_connection,
    init_db,
    verify_schema,
    DEFAULT_DB_PATH,
    DEFAULT_SCHEMA_PATH,
)


def run_validation():
    print("=== NPTEL Practice Hub Phase 1 Comprehensive Validation ===")
    results = {}

    # 1. Database Path Resolution Test
    print("\n[1] Testing database path resolution...")
    try:
        expected_db = (BASE_DIR / "instance" / "nptel_hub.db").resolve()
        actual_db = DEFAULT_DB_PATH.resolve()
        assert actual_db == expected_db, f"Path mismatch: {actual_db} != {expected_db}"
        assert DEFAULT_SCHEMA_PATH.resolve() == (BASE_DIR / "schema.sql").resolve()
        print(f" -> PASS: DEFAULT_DB_PATH correctly resolved relative to file: {actual_db}")
        results["Database path resolution"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Database path resolution"] = "FAIL"

    # 2. Safe Database Re-initialization (Idempotency)
    print("\n[2] Testing safe database re-initialization...")
    try:
        init_db()
        print(" -> PASS: init_db() executed safely without error.")
        results["Safe database re-initialization"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Safe database re-initialization"] = "FAIL"

    # 3. Required Tables and Columns
    print("\n[3] Testing required tables and columns...")
    try:
        conn = get_db_connection()
        verification = verify_schema(conn)
        assert verification["is_valid"], f"Missing tables: {verification['missing_tables']}"
        expected_columns = {
            "weeks": ["week_number", "title", "total_questions"],
            "questions": [
                "id",
                "week_number",
                "question_number",
                "question_order",
                "question_text",
                "marks",
                "is_verified",
                "flag_reason",
            ],
            "options": [
                "id",
                "question_id",
                "option_letter",
                "option_order",
                "option_text",
                "is_correct",
            ],
            "practice_sessions": [
                "session_id",
                "created_at",
                "selected_weeks",
                "test_type",
                "question_ids",
                "option_orders",
                "is_submitted",
            ],
        }
        for table, cols in expected_columns.items():
            actual_cols = verification["table_columns"].get(table, [])
            for col in cols:
                assert col in actual_cols, f"Table '{table}' is missing column '{col}'"
        print(" -> PASS: All expected tables and columns exist.")
        results["Required tables and columns"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Required tables and columns"] = "FAIL"

    # 4. Foreign-Key Enforcement
    print("\n[4] Testing foreign-key enforcement...")
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys;")
        fk_status = cursor.fetchone()
        assert fk_status and fk_status[0] == 1, "Foreign keys are not enabled in connection."
        try:
            cursor.execute(
                "INSERT INTO questions (week_number, question_number, question_order, question_text) "
                "VALUES (9999, 1, 1, 'Orphan Question');"
            )
            raise AssertionError("FAIL: Foreign key constraint did not reject orphan question.")
        except sqlite3.IntegrityError:
            print(" -> PASS: Foreign key correctly rejected insertion of question with non-existent week_number.")
        results["Foreign-key enforcement"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Foreign-key enforcement"] = "FAIL"

    # Set up temporary test records for constraint testing
    cursor.execute("INSERT INTO weeks (week_number, title, total_questions) VALUES (999, 'Temp Test Week', 1);")
    cursor.execute(
        "INSERT INTO questions (week_number, question_number, question_order, question_text, marks, is_verified) "
        "VALUES (999, 1, 1, 'Temp Question 1', 1.0, 1);"
    )
    test_q_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO options (question_id, option_letter, option_order, option_text, is_correct) "
        "VALUES (?, 'a', 1, 'Option A Text', 1);",
        (test_q_id,)
    )
    conn.commit()

    # 5. Duplicate Question-Number Prevention
    print("\n[5] Testing duplicate question-number prevention...")
    try:
        try:
            cursor.execute(
                "INSERT INTO questions (week_number, question_number, question_order, question_text) "
                "VALUES (999, 1, 2, 'Duplicate Question 1');"
            )
            raise AssertionError("FAIL: Uniqueness constraint did not reject duplicate (week_number, question_number).")
        except sqlite3.IntegrityError:
            print(" -> PASS: Correctly blocked duplicate (week_number, question_number).")
        results["Duplicate question-number prevention"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Duplicate question-number prevention"] = "FAIL"

    # 6. Duplicate Option-Letter Prevention
    print("\n[6] Testing duplicate option-letter prevention...")
    try:
        try:
            cursor.execute(
                "INSERT INTO options (question_id, option_letter, option_order, option_text) "
                "VALUES (?, 'a', 2, 'Duplicate Option A with different order');",
                (test_q_id,)
            )
            raise AssertionError("FAIL: Uniqueness constraint did not reject duplicate (question_id, option_letter).")
        except sqlite3.IntegrityError:
            print(" -> PASS: Correctly blocked duplicate (question_id, option_letter).")
        results["Duplicate option-letter prevention"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Duplicate option-letter prevention"] = "FAIL"

    # 7. Duplicate Option-Order Prevention
    print("\n[7] Testing duplicate option-order prevention...")
    try:
        try:
            # Attempt to insert an option with different letter ('b') but identical option_order (1) for the same question
            cursor.execute(
                "INSERT INTO options (question_id, option_letter, option_order, option_text) "
                "VALUES (?, 'b', 1, 'Option B with duplicate order 1');",
                (test_q_id,)
            )
            raise AssertionError("FAIL: Uniqueness constraint did not reject duplicate (question_id, option_order).")
        except sqlite3.IntegrityError:
            print(" -> PASS: Correctly blocked duplicate (question_id, option_order).")
        results["Duplicate option-order prevention"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Duplicate option-order prevention"] = "FAIL"

    # 8. Cascade Deletion
    print("\n[8] Testing cascade deletion...")
    try:
        cursor.execute("DELETE FROM questions WHERE id = ?;", (test_q_id,))
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM options WHERE question_id = ?;", (test_q_id,))
        orphans = cursor.fetchone()[0]
        assert orphans == 0, f"Cascade deletion failed; {orphans} orphaned options found."
        print(" -> PASS: Cascade deletion verified (dependent options automatically purged).")
        results["Cascade deletion"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Cascade deletion"] = "FAIL"

    # Clean up temporary test week
    cursor.execute("DELETE FROM weeks WHERE week_number = 999;")
    conn.commit()

    # 9. Preservation of Existing Database Data
    print("\n[9] Testing preservation of existing database data across operations...")
    try:
        # Insert a sentinel record to verify table content is not erased on re-init
        cursor.execute("INSERT INTO weeks (week_number, title, total_questions) VALUES (888, 'Persistent Sentinel', 5);")
        conn.commit()

        # Re-initialize the database schema
        init_db()

        cursor.execute("SELECT title, total_questions FROM weeks WHERE week_number = 888;")
        row = cursor.fetchone()
        assert row is not None, "Existing data was lost during re-initialization!"
        assert row["title"] == "Persistent Sentinel"
        assert row["total_questions"] == 5

        # Clean up sentinel record
        cursor.execute("DELETE FROM weeks WHERE week_number = 888;")
        conn.commit()
        print(" -> PASS: Existing database data strictly preserved across re-initialization.")
        results["Preservation of existing database data"] = "PASS"
    except Exception as e:
        print(f" -> FAIL: {e}")
        results["Preservation of existing database data"] = "FAIL"

    conn.close()

    print("\n=== Phase 1 Validation Summary ===")
    all_passed = True
    for test_name, status in results.items():
        print(f" - {test_name}: {status}")
        if status != "PASS":
            all_passed = False

    if not all_passed:
        raise SystemExit("One or more validation checks failed!")

    print("\nAll 9 Phase 1 validation checks PASSED successfully.")

if __name__ == "__main__":
    run_validation()
