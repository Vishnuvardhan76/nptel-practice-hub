"""PostgreSQL connection helpers for NPTEL Practice Hub."""

import os
import psycopg
from psycopg.rows import dict_row


def get_postgres_connection(database_url=None):
    """Connect to PostgreSQL using an explicit URL or DATABASE_URL."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")

    try:
        connection = psycopg.connect(
            url,
            row_factory=dict_row,
            connect_timeout=10,
        )
        return CompatibleConnection(connection)
    except psycopg.Error as exc:
        # Avoid exposing the connection URL or credentials.
        raise RuntimeError("Could not connect to PostgreSQL.") from exc


class CompatibleCursor:
    """Translate SQLite-style ? placeholders for PostgreSQL queries."""

    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _translate(sql):
        # Replace placeholders only outside SQL strings and comments.
        result = []
        i = 0
        state = "normal"

        while i < len(sql):
            ch = sql[i]
            nxt = sql[i + 1] if i + 1 < len(sql) else ""

            if state == "normal":
                if ch == "'":
                    state = "single"
                    result.append(ch)
                elif ch == '"':
                    state = "double"
                    result.append(ch)
                elif ch == "-" and nxt == "-":
                    state = "line_comment"
                    result.extend([ch, nxt])
                    i += 1
                elif ch == "/" and nxt == "*":
                    state = "block_comment"
                    result.extend([ch, nxt])
                    i += 1
                elif ch == "?":
                    result.append("%s")
                else:
                    result.append(ch)
            elif state == "single":
                result.append(ch)
                if ch == "'" and nxt == "'":
                    result.append(nxt)
                    i += 1
                elif ch == "'":
                    state = "normal"
            elif state == "double":
                result.append(ch)
                if ch == '"' and nxt == '"':
                    result.append(nxt)
                    i += 1
                elif ch == '"':
                    state = "normal"
            elif state == "line_comment":
                result.append(ch)
                if ch == "\n":
                    state = "normal"
            elif state == "block_comment":
                result.append(ch)
                if ch == "*" and nxt == "/":
                    result.append(nxt)
                    i += 1
                    state = "normal"

            i += 1

        return "".join(result)

    def execute(self, query, params=None):
        query = self._translate(query)
        if params is None:
            return self._cursor.execute(query)
        return self._cursor.execute(query, params)

    def executemany(self, query, params):
        return self._cursor.executemany(self._translate(query), params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class CompatibleConnection:
    """Provide the cursor interface used by the existing Flask app."""

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return CompatibleCursor(self._connection.cursor())

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._connection.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name):
        return getattr(self._connection, name)
