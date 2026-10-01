"""Calculation service -- chains "tokenization -> parsing -> evaluation" into one pipeline.

This layer is thin and does little beyond orchestration. Its value is that:

    1. It exposes **a single public method**, ``calculate(expression)``, so callers
       (the HTTP layer, tests, the command line) need not know there are three
       steps inside.
    2. It **converts every exception in one place**: the lower layers raise business
       exceptions such as InvalidExpressionError, and this layer makes sure they
       bubble up in a uniform shape, so the HTTP layer only has to catch CalcError.
    3. It is the **single entry point for result formatting**: whether a result goes
       to the front-end or into the database it passes through ``format_result``, so
       "20" can never appear as "20.0" in one place and "20" in another.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.calculator.evaluator import evaluate, format_result
from src.calculator.parser import parse
from src.common.errors import CalcError, InvalidExpressionError


@dataclass(frozen=True)
class CalculationOutcome:
    """The complete outcome of one calculation.

    expression  the raw expression entered by the user (kept as-is, never normalized)
    result      the result, as a normalized **string**
    value       the same result in numeric form (used for the JSON number in the API response)
    """

    expression: str
    result: str
    value: Decimal


class CalculatorService:
    """Calculation service.

    Stateless: one instance can be shared by many requests and need not be created
    for each one. (The current implementation really has no instance attributes, so
    no locking is needed in a multi-threaded HTTP environment either.)
    """

    def calculate(self, expression: str) -> CalculationOutcome:
        """Calculate one expression.

        Args:
            expression: the expression entered by the user, for example "1+2*3"

        Returns:
            CalculationOutcome

        Raises:
            InvalidExpressionError: the expression is not valid (syntax error,
                illegal character, unbalanced parentheses)
            DivisionByZeroError: the divisor is zero
        """
        if not isinstance(expression, str):
            raise InvalidExpressionError("Expression must be a string")

        # Step 1: tokenize (tokenizer.py)
        # Step 2: build the syntax tree (parser.py)
        # Step 3: evaluate (evaluator.py)
        #
        # The three steps are written out rather than chained into a single line,
        # so that logging or caching can later be inserted between them without
        # changing the structure.
        tree = parse(expression)
        raw_value = evaluate(tree)
        text = format_result(raw_value)

        return CalculationOutcome(
            expression=expression,
            result=text,
            value=raw_value,
        )

    def try_calculate(self, expression: str) -> tuple[CalculationOutcome | None, CalcError | None]:
        """The non-raising version of calculate; returns a (result, error) pair.

        Why two versions exist:
            The HTTP layer can use try_calculate and skip a level of
            try/except, which reads flatter; tests can use calculate and assert
            on the exception type directly, which is more immediate. Both are
            kept, each used where it fits best.

        Returns:
            (result, None) or (None, error)
        """
        try:
            return self.calculate(expression), None
        except CalcError as exc:
            return None, exc
