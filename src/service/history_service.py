"""History service -- orchestration of calculation and persistence.

Division of labour:
    CalculatorService   computes only (stateless, never touches the database)
    SqliteStore         stores only (does not care where a result came from)
    HistoryService      wires the two together: store a record after each
                        successful calculation, and expose history query/delete

Why "compute" and "store" are kept apart:
    1. The computing part can be tested without a database
       (tests/test_calculator.py needs no database at all);
    2. The storing part can be tested without the calculator
       (tests/test_store.py inserts fake data directly);
    3. If automatic history saving is ever dropped, only this layer changes and
       neither of the two lower modules is touched.

One design decision: **a failed calculation writes no history**.
    Only a successfully computed result is stored. The reasoning: history means
    "expressions that were computed", and an invalid expression is not a valid
    calculation, so recording it would only confuse the user.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.common.errors import RecordNotFoundError
from src.model.sqlite_store import SqliteStore
from src.service.calculator_service import CalculationOutcome, CalculatorService


class HistoryService:
    """Calculation plus history persistence."""

    def __init__(self, db_path: str | Path, calculator: CalculatorService | None = None) -> None:
        self._store = SqliteStore(db_path)
        self._calculator = calculator or CalculatorService()

    def init(self) -> None:
        """Called once at start-up: create the table."""
        self._store.init_schema()

    # ---------------------------------------------------------------- compute + store

    def calculate_and_save(self, expression: str) -> CalculationOutcome:
        """Calculate an expression and store the result in the database.

        Args:
            expression: the expression entered by the user

        Returns:
            The calculation outcome

        Raises:
            InvalidExpressionError / DivisionByZeroError: the expression is not valid
                (in that case **nothing is written to the database**)
        """
        outcome = self._calculator.calculate(expression)

        # History is written only after a result has been computed successfully.
        # Sitting after calculate means this line is never reached when an
        # exception is raised -- that is how "no write on failure" is implemented,
        # with no extra check needed.
        self._store.insert(outcome.expression, outcome.result)

        return outcome

    # ---------------------------------------------------------------- read

    def list_history(self, limit: int = 50, keyword: str | None = None) -> dict:
        """Fetch the history list (including the total, for front-end paging)."""
        records = self._store.list_recent(limit=limit, keyword=keyword)
        return {
            "items": records,
            "total": self._store.count(),
            "limit": limit,
            "keyword": keyword or "",
        }

    def stats(self) -> dict:
        """Statistics (extended feature)."""
        return self._store.stats()

    # ---------------------------------------------------------------- delete

    def delete_history(self, record_id: int) -> None:
        """Delete one history record.

        Raises:
            RecordNotFoundError: no record with that id exists
                -- an exception is raised instead of returning False so that the
                   HTTP layer can reply 404 from the error code in one place
                   instead of checking return values everywhere.
        """
        if not self._store.delete(record_id):
            raise RecordNotFoundError(f"History record {record_id} does not exist or was deleted")

    def delete_all_history(self) -> int:
        """Clear all history and return the number of deleted records (extended feature)."""
        return self._store.delete_all()
