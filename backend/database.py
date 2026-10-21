"""
NPTEL Practice Hub - Database Operations & Helpers
Handles SQLite connections, schema initialization, and safe query helpers.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

# Default paths
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "nptel_hub.db"
DEFAULT_SCHEMA_PATH = BASE_DIR / "schema.sql"


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Safely and idempotently applies non-destructive schema migrations.
    Never drops, recreates, or alters existing course data or prior attempts.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='practice_sessions';")
    if not cursor.fetchone():
        return
    cursor.execute("PRAGMA table_info(practice_sessions);")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    new_columns = [
        ("user_answers", "TEXT DEFAULT '{}'"),
        ("submitted_at", "TIMESTAMP"),
        ("score", "REAL DEFAULT 0.0"),
        ("total_marks", "REAL DEFAULT 0.0"),
        ("correct_count", "INTEGER DEFAULT 0"),
        ("incorrect_count", "INTEGER DEFAULT 0"),
        ("unanswered_count", "INTEGER DEFAULT 0"),
        ("client_id", "TEXT"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE practice_sessions ADD COLUMN {col_name} {col_def};")
    conn.commit()


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Creates and returns a connection to the SQLite database.
    Enables foreign keys and sets row_factory to sqlite3.Row.
    Applies safe, idempotent schema migrations if needed.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    # Ensure parent directory exists (e.g., instance/)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(target_path))
        conn.row_factory = sqlite3.Row
        # Explicitly enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        run_migrations(conn)
        return conn
    except sqlite3.Error as e:
        raise RuntimeError(f"Failed to connect to database at {target_path}: {e}") from e


def init_db(
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None
) -> None:
    """
    Initializes the SQLite database using schema.sql.
    Safe for repeated runs without dropping existing valid tables.
    """
    target_db = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_schema = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH

    if not target_schema.exists():
        raise FileNotFoundError(f"Schema file not found at: {target_schema}")

    try:
        with open(target_schema, "r", encoding="utf-8") as f:
            schema_sql = f.read()
    except OSError as e:
        raise RuntimeError(f"Error reading schema file {target_schema}: {e}") from e

    conn = get_db_connection(target_db)
    try:
        with conn:
            conn.executescript(schema_sql)
    except sqlite3.Error as e:
        raise RuntimeError(f"Database initialization failed: {e}") from e
    finally:
        conn.close()


def verify_schema(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Verifies that all required tables exist and foreign keys are active.
    Returns a dictionary of inspection results.
    """
    cursor = conn.cursor()

    # Check foreign keys pragma
    cursor.execute("PRAGMA foreign_keys;")
    fk_status = cursor.fetchone()
    foreign_keys_enabled = bool(fk_status[0]) if fk_status else False

    # Check required tables
    expected_tables = ["weeks", "questions", "options", "practice_sessions"]
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = {row["name"] for row in cursor.fetchall()}

    missing_tables = [t for t in expected_tables if t not in existing_tables]

    # Inspect columns per expected table
    table_columns: Dict[str, List[str]] = {}
    for table in expected_tables:
        if table in existing_tables:
            cursor.execute(f"PRAGMA table_info({table});")
            table_columns[table] = [row["name"] for row in cursor.fetchall()]

    return {
        "foreign_keys_enabled": foreign_keys_enabled,
        "existing_tables": sorted(list(existing_tables)),
        "missing_tables": missing_tables,
        "table_columns": table_columns,
        "is_valid": foreign_keys_enabled and len(missing_tables) == 0,
    }


if __name__ == "__main__":
    print(f"Initializing database at: {DEFAULT_DB_PATH}")
    init_db()

    with get_db_connection() as connection:
        verification = verify_schema(connection)
        print("Schema verification results:")
        print(f" - Foreign Keys Enabled: {verification['foreign_keys_enabled']}")
        print(f" - Existing Tables: {verification['existing_tables']}")
        print(f" - Missing Tables: {verification['missing_tables']}")
        print(f" - Schema Valid: {verification['is_valid']}")
        if not verification["is_valid"]:
            raise SystemExit("Schema verification failed!")
        print("Database initialized and verified successfully.")
