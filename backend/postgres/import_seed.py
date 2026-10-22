"""Import validated course seed data into an empty PostgreSQL database."""

import os
import sqlite3
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parents[2]
SEED_DB = ROOT / "deployment-work" / "course_seed.db"
SCHEMA = Path(__file__).with_name("schema.sql")


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("STOP: DATABASE_URL is not configured.")
    if not SEED_DB.is_file():
        raise SystemExit(f"STOP: seed database not found: {SEED_DB}")
    if not SCHEMA.is_file():
        raise SystemExit(f"STOP: PostgreSQL schema not found: {SCHEMA}")

    source = sqlite3.connect(f"file:{SEED_DB.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row

    try:
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"STOP: seed database integrity check failed: {integrity}")

        weeks = source.execute(
            "SELECT week_number, title, total_questions FROM weeks ORDER BY week_number"
        ).fetchall()
        questions = source.execute(
            """SELECT id, week_number, question_number, question_order,
                      question_text, marks, is_verified, flag_reason
               FROM questions ORDER BY id"""
        ).fetchall()
        options = source.execute(
            """SELECT id, question_id, option_letter, option_order,
                      option_text, is_correct
               FROM options ORDER BY id"""
        ).fetchall()

        if (len(weeks), len(questions), len(options)) != (12, 120, 480):
            raise SystemExit(
                "STOP: unexpected seed counts: "
                f"weeks={len(weeks)}, questions={len(questions)}, options={len(options)}"
            )

        invalid = source.execute("""
            SELECT COUNT(*) FROM (
                SELECT q.id
                FROM questions q
                LEFT JOIN options o ON o.question_id = q.id
                GROUP BY q.id
                HAVING COUNT(o.id) != 4 OR SUM(o.is_correct) != 1
            )
        """).fetchone()[0]
        if invalid:
            raise SystemExit(f"STOP: {invalid} questions have invalid option/answer counts.")

        with psycopg.connect(url, connect_timeout=10) as target:
            with target.cursor() as cur:
                schema_sql = SCHEMA.read_text(encoding="utf-8-sig").lstrip("\uFEFF")
                import re
                schema_sql = re.sub(r"(?m)^\s*--.*$", "", schema_sql)
                for statement in schema_sql.split(";"):
                    statement = statement.strip()
                    if statement and statement.upper().startswith("CREATE TABLE"):
                        cur.execute(statement)
                cur.execute("""
                    SELECT
                      (SELECT COUNT(*) FROM weeks),
                      (SELECT COUNT(*) FROM questions),
                      (SELECT COUNT(*) FROM options),
                      (SELECT COUNT(*) FROM practice_sessions)
                """)
                existing = cur.fetchone()
                if existing != (0, 0, 0, 0):
                    raise SystemExit(
                        "STOP: target database is not empty. "
                        f"Existing row counts: {existing}. Nothing imported."
                    )

                

                cur.executemany(
                    """INSERT INTO weeks (week_number, title, total_questions)
                       VALUES (%s, %s, %s)""",
                    [tuple(row) for row in weeks],
                )
                cur.executemany(
                    """INSERT INTO questions
                       (id, week_number, question_number, question_order,
                        question_text, marks, is_verified, flag_reason)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    [tuple(row) for row in questions],
                )
                cur.executemany(
                    """INSERT INTO options
                       (id, question_id, option_letter, option_order,
                        option_text, is_correct)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    [tuple(row) for row in options],
                )

                cur.execute("""
                    SELECT
                      (SELECT COUNT(*) FROM weeks),
                      (SELECT COUNT(*) FROM questions),
                      (SELECT COUNT(*) FROM options),
                      (SELECT COUNT(*) FROM practice_sessions)
                """)
                counts = cur.fetchone()
                if counts != (12, 120, 480, 0):
                    raise RuntimeError(f"Post-import count validation failed: {counts}")

                cur.execute("""
                    SELECT COUNT(*)
                    FROM questions q
                    WHERE (SELECT COUNT(*) FROM options o WHERE o.question_id = q.id) != 4
                       OR (SELECT COALESCE(SUM(o.is_correct), 0)
                           FROM options o WHERE o.question_id = q.id) != 1
                """)
                if cur.fetchone()[0] != 0:
                    raise RuntimeError("Post-import answer-key validation failed.")

                for table in ("questions", "options"):
                    cur.execute(
                        f"""SELECT setval(
                              pg_get_serial_sequence('{table}', 'id'),
                              COALESCE((SELECT MAX(id) FROM {table}), 1),
                              EXISTS (SELECT 1 FROM {table})
                            )"""
                    )

        print("PASS: seed import committed and verified.")
        print("Weeks: 12 | Questions: 120 | Options: 480")
        print("Every question has four options and exactly one correct answer.")
        print("Practice sessions imported: 0")

    finally:
        source.close()


if __name__ == "__main__":
    main()
