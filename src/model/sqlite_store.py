"""SQLite storage layer -- persistence of the calculation history.

The assignment requires that calculation history be persisted in the back-end
database, so history **must live in the back-end database**. It must not be kept
in the front-end localStorage, and it must not live only in memory (which is lost
as soon as the process restarts).

Why SQLite:
    1. It ships with the Python standard library (``import sqlite3``), so no
       database service has to be installed;
    2. The data lives in a single file, so copying that file is a complete backup;
    3. Whoever receives the code can run it without setting up MySQL.

This module only decides "how to store", never "what counts as valid" -- that is
the service layer's job.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

# Schema definition.
#
# Why result is stored as TEXT instead of REAL:
#   Results are Decimal, and storing them as REAL turns them into binary
#   floating point, so 0.1+0.2 might not come back out as 0.3.
#   TEXT keeps the decimal exact and the value is converted back to Decimal on read.
#
# created_at is stored as ISO-8601 text, which sorts well and displays directly.
SCHEMA = """
CREATE TABLE IF NOT EXISTS calculation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expression  TEXT    NOT NULL,
    result      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

-- Listing history in reverse time order is the most frequent operation (the front end
-- pulls the latest records as soon as it opens), so created_at is indexed.
CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON calculation_history (created_at DESC);
"""


class SqliteStore:
    """SQLite storage for the calculation history.

    Usage:
        store = SqliteStore("data/calculator.db")
        store.init_schema()
        record = store.insert("12+8", "20")

    About connections:
        Every operation opens a new connection and closes it again. Opening a
        local SQLite file is extremely cheap, and this avoids **sharing one
        connection across the multi-threaded HTTP environment** (sqlite3
        connection objects cannot be used across threads by default), which
        removes a whole class of concurrency problems.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    # ---------------------------------------------------------------- infrastructure

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection; commit and close it automatically when done.

        A contextmanager guarantees the connection is closed properly even when
        an exception is raised, and callers only have to write
        with self._connect() as conn: ...
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        # row_factory lets query results be read by column name: row["expression"]
        # Without it only positional access works -- row[1] -- which is far less readable.
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create the table (idempotent: a no-op when the table already exists).

        Called once when the service starts. IF NOT EXISTS makes repeated calls safe.
        """
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- insert

    def insert(self, expression: str, result: str) -> dict:
        """Insert one calculation record.

        Args:
            expression: the expression entered by the user (stored as-is)
            result: the normalized result string

        Returns:
            The complete newly inserted record (including the auto-increment id
            and the creation time)
        """
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO calculation_history (expression, result, created_at) "
                "VALUES (?, ?, ?)",
                (expression, result, created_at),
            )
            new_id = int(cursor.lastrowid or 0)

        return {
            "id": new_id,
            "expression": expression,
            "result": result,
            "createdAt": created_at,
        }

    # ---------------------------------------------------------------- read

    def list_recent(self, limit: int = 50, keyword: str | None = None) -> list[dict]:
        """Fetch history records in reverse chronological order.

        Args:
            limit: the maximum number of records to fetch
            keyword: optional. Fuzzy match against the expression (the extended
                "history search" feature)

        Returns:
            The record list, newest first
        """
        sql = "SELECT id, expression, result, created_at FROM calculation_history"
        params: list[object] = []

        if keyword:
            sql += " WHERE expression LIKE ?"
            params.append(f"%{keyword}%")

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._to_dict(row) for row in rows]

    def count(self, keyword: str | None = None) -> int:
        """Count the records (used by paging and the statistics panel)."""
        sql = "SELECT COUNT(*) AS n FROM calculation_history"
        params: list[object] = []
        if keyword:
            sql += " WHERE expression LIKE ?"
            params.append(f"%{keyword}%")

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()

        return int(row["n"]) if row else 0

    def get(self, record_id: int) -> dict | None:
        """Fetch one record by id; returns None when it does not exist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, expression, result, created_at FROM calculation_history WHERE id = ?",
                (record_id,),
            ).fetchone()

        return self._to_dict(row) if row else None

    # ---------------------------------------------------------------- delete

    def delete(self, record_id: int) -> bool:
        """Delete one record.

        Returns:
            True means a row really was deleted; False means that id never existed.
            The boolean is returned so the service layer can decide between 404 and 204.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM calculation_history WHERE id = ?", (record_id,)
            )
            deleted = cursor.rowcount

        return deleted > 0

    def delete_all(self) -> int:
        """Clear all history (extended feature). Returns the number of deleted records.

        Implementation note: the count must be taken **before** the delete.
        This started out as "delete, then read cursor.rowcount", but SQLite may
        return -1 for rowcount on a full-table DELETE, and once the rows are gone
        the original count cannot be queried any more.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM calculation_history"
            ).fetchone()
            before = int(row["n"]) if row else 0
            conn.execute("DELETE FROM calculation_history")

        return before

    # ---------------------------------------------------------------- statistics

    def stats(self) -> dict:
        """Statistics (used by the extended statistics panel)."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM calculation_history"
            ).fetchone()["n"]

            # Count how often each operator appears in the expressions.
            # Accumulated with SQL LIKE instead of pulling every record into Python and looping.
            operator_counts = {}
            for op, label in (("+", "add"), ("-", "subtract"), ("*", "multiply"), ("/", "divide")):
                n = conn.execute(
                    "SELECT COUNT(*) AS n FROM calculation_history WHERE expression LIKE ?",
                    (f"%{op}%",),
                ).fetchone()["n"]
                operator_counts[label] = int(n)

        return {"total": int(total), "byOperator": operator_counts}

    # ---------------------------------------------------------------- internal helpers

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        """Turn a database row into the dictionary used by the front-end.

        Field names use camelCase (createdAt) to match the agreement with the
        front-end, while the database column names stay snake_case (created_at),
        as is conventional in SQL.
        """
        return {
            "id": int(row["id"]),
            "expression": row["expression"],
            "result": row["result"],
            "createdAt": row["created_at"],
        }
