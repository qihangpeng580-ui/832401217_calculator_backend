"""Standalone database creation script -- prepares the database file without starting the service.

Purpose:
    · create the database before deployment, instead of on the first request (which works too)
    · inspect the current state of the database (how many records there are)
    · clear all history (with a confirmation prompt)

Usage:
    py -3.12 init_db.py                   create the database / show its state
    py -3.12 init_db.py --clear            create it and clear all history
    py -3.12 init_db.py --db other.db      use another file
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model.sqlite_store import SqliteStore  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "calculator.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="init_db.py",
        description="Initialize the SQLite database of the calculator back end",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"database file path (default {DEFAULT_DB})",
    )
    parser.add_argument("--clear", action="store_true", help="clear all history records")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    store = SqliteStore(db_path)

    existed = db_path.exists()
    store.init_schema()
    print(f"Database: {db_path}")
    print(f"State: {'already exists, schema confirmed' if existed else 'newly created'}")

    if args.clear:
        deleted = store.delete_all()
        print(f"Cleared {deleted} history records")

    total = store.count()
    print(f"History records now: {total}")

    if total:
        print("\nMost recent 5:")
        for record in store.list_recent(limit=5):
            print(
                f"  [{record['id']}] {record['expression']} = {record['result']}   "
                f"({record['createdAt']})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
