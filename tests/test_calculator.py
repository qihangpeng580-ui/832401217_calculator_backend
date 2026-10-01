"""Tests: the complete calculation pipeline (lexical -> syntax -> evaluation -> formatting).

Run (from the project root):
    py -3.12 -m unittest tests.test_calculator -v

This is the group that most resembles assignment acceptance:
    the first few test classes are taken directly from the example expressions
    given in the assignment post.

Division of labour with test_parser.py:
    test_parser.py  checks only the **shape of the syntax tree** (left associativity,
                    correct precedence)
    this file       checks that the **final computed number** is correct
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.common.errors import DivisionByZeroError, InvalidExpressionError
from src.service.calculator_service import CalculatorService

svc = CalculatorService()


def calc(expression: str) -> str:
    """Helper: evaluate an expression and return the string result."""
    return svc.calculate(expression).result


class TestAssignmentExamples(unittest.TestCase):
    """The example expressions given verbatim in the assignment post.

    Original list (Part 1, features 1 and 2):
        12 + 8
        1 + 2 * 3
        (1 + 2) * 3
        10 / 2 + 7
        8 - 3 * 2
        -5 + 8
        3 * -2
    """

    def test_basic_addition(self) -> None:
        self.assertEqual(calc("12+8"), "20")

    def test_precedence(self) -> None:
        self.assertEqual(calc("1+2*3"), "7")

    def test_parentheses(self) -> None:
        self.assertEqual(calc("(1+2)*3"), "9")

    def test_division_then_addition(self) -> None:
        self.assertEqual(calc("10/2+7"), "12")

    def test_subtraction_and_multiplication(self) -> None:
        self.assertEqual(calc("8-3*2"), "2")

    def test_unary_minus_at_front(self) -> None:
        self.assertEqual(calc("-5+8"), "3")

    def test_unary_minus_after_operator(self) -> None:
        self.assertEqual(calc("3*-2"), "-6")

    def test_with_spaces(self) -> None:
        """The assignment examples are written with spaces; the back-end must accept spaces."""
        self.assertEqual(calc("1 + 2 * 3"), "7")
        self.assertEqual(calc("( 1 + 2 ) * 3"), "9")


class TestFourOperations(unittest.TestCase):
    """Basic correctness of the four arithmetic operations."""

    def test_addition(self) -> None:
        self.assertEqual(calc("2+3"), "5")

    def test_subtraction(self) -> None:
        self.assertEqual(calc("10-4"), "6")

    def test_multiplication(self) -> None:
        self.assertEqual(calc("6*7"), "42")

    def test_division(self) -> None:
        self.assertEqual(calc("20/4"), "5")

    def test_subtraction_to_negative(self) -> None:
        self.assertEqual(calc("3-10"), "-7")

    def test_zero_result(self) -> None:
        self.assertEqual(calc("5-5"), "0")


class TestDecimals(unittest.TestCase):
    """Decimals -- this is where the value of Decimal over float shows."""

    def test_decimal_addition(self) -> None:
        """This is the direct reason for choosing Decimal.

        With float, 0.1+0.2 gives 0.30000000000000004, while a calculator has to
        show 0.3 -- otherwise any user sees at a glance that it is broken.
        """
        self.assertEqual(calc("0.1+0.2"), "0.3")

    def test_decimal_subtraction(self) -> None:
        self.assertEqual(calc("1.1-0.9"), "0.2")

    def test_multiple_decimals(self) -> None:
        self.assertEqual(calc("3.5+1.25"), "4.75")

    def test_decimal_multiplication(self) -> None:
        self.assertEqual(calc("1.5*4"), "6")

    def test_decimal_division(self) -> None:
        self.assertEqual(calc("7.5/2.5"), "3")

    def test_division_not_exact(self) -> None:
        """A non-terminating division: keep a limited number of decimal places,
        never a long string.
        """
        result = calc("1/3")
        self.assertTrue(result.startswith("0.333333"))
        self.assertLessEqual(len(result), 15)

    def test_trailing_zeros_removed(self) -> None:
        """20.00 must display as 20, not as 20.00."""
        self.assertEqual(calc("10.00*2"), "20")

    def test_leading_dot(self) -> None:
        self.assertEqual(calc(".5+.5"), "1")

    def test_trailing_dot(self) -> None:
        self.assertEqual(calc("1.+1"), "2")


class TestPrecedenceAndParentheses(unittest.TestCase):
    """Precedence and parentheses."""

    def test_multiplication_before_addition(self) -> None:
        self.assertEqual(calc("2+3*4"), "14")

    def test_multiplication_before_subtraction(self) -> None:
        self.assertEqual(calc("20-3*4"), "8")

    def test_division_before_addition(self) -> None:
        self.assertEqual(calc("2+10/5"), "4")

    def test_parentheses_override(self) -> None:
        self.assertEqual(calc("(2+3)*4"), "20")

    def test_nested_parentheses(self) -> None:
        self.assertEqual(calc("2*(3+(4-1))"), "12")

    def test_left_associativity_subtraction(self) -> None:
        """1-2-3 = -4 (left to right), not 1-(2-3) = 2."""
        self.assertEqual(calc("1-2-3"), "-4")

    def test_left_associativity_division(self) -> None:
        """100/5/2 = 10, not 100/(5/2) = 40."""
        self.assertEqual(calc("100/5/2"), "10")

    def test_complex_expression(self) -> None:
        self.assertEqual(calc("((1+2)*(3+4))-5"), "16")


class TestUnaryOperators(unittest.TestCase):
    """Unary plus and minus."""

    def test_negative_number(self) -> None:
        self.assertEqual(calc("-5"), "-5")

    def test_positive_sign(self) -> None:
        self.assertEqual(calc("+5"), "5")

    def test_negative_in_parentheses(self) -> None:
        self.assertEqual(calc("(-5)+8"), "3")

    def test_multiply_by_negative(self) -> None:
        self.assertEqual(calc("3*-2"), "-6")

    def test_negative_times_negative(self) -> None:
        self.assertEqual(calc("-3*-2"), "6")

    def test_double_negative(self) -> None:
        self.assertEqual(calc("--5"), "5")

    def test_negative_parenthesized_expression(self) -> None:
        self.assertEqual(calc("-(1+2)"), "-3")

    def test_frontend_negation_form(self) -> None:
        """The front-end +/- key produces forms such as (-3); the back-end must handle them."""
        self.assertEqual(calc("5+(-3)"), "2")
        self.assertEqual(calc("5*(-3)"), "-15")


class TestDivisionByZero(unittest.TestCase):
    """Division by zero must produce the agreed error instead of a raw Decimal library exception.

    The front-end ui.js has an error-code table in which `DIVISION_BY_ZERO` maps
    to the user-facing message shown to users.
    """

    def test_simple_division_by_zero(self) -> None:
        with self.assertRaises(DivisionByZeroError) as ctx:
            calc("10/0")
        self.assertEqual(ctx.exception.error_code, "DIVISION_BY_ZERO")
        self.assertEqual(ctx.exception.http_status, 422)

    def test_division_by_zero_decimal(self) -> None:
        with self.assertRaises(DivisionByZeroError):
            calc("10/0.0")

    def test_division_by_expression_that_is_zero(self) -> None:
        """A divisor that is an expression evaluating to zero must be caught too."""
        with self.assertRaises(DivisionByZeroError):
            calc("10/(5-5)")

    def test_division_by_zero_inside_expression(self) -> None:
        with self.assertRaises(DivisionByZeroError):
            calc("1+2/0")

    def test_zero_divided_by_something_is_fine(self) -> None:
        """Zero as the dividend is fine."""
        self.assertEqual(calc("0/5"), "0")


class TestInvalidExpressions(unittest.TestCase):
    """Invalid expressions -- the assignment requires "Invalid expression handling"."""

    def test_empty(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("")

    def test_only_spaces(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("   ")

    def test_letters(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1+a")

    def test_trailing_operator(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1+2*")

    def test_unclosed_parenthesis(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("(1+2")

    def test_extra_closing_parenthesis(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1+2)")

    def test_two_operators(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1+*2")

    def test_multiple_dots_in_one_number(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1.2.3")

    def test_only_operator(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("*")

    def test_error_code_is_invalid_expression(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            calc("1+")
        self.assertEqual(ctx.exception.error_code, "INVALID_EXPRESSION")
        self.assertEqual(ctx.exception.http_status, 400)


class TestSecurity(unittest.TestCase):
    """Security: user input must never be executed as code.

    The assignment explicitly forbids eval/exec. This group is written from an
    attacker's point of view: even when a piece of Python code is submitted as an
    expression, the only outcome is "illegal character" and nothing is executed.
    """

    def test_import_statement_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("__import__('os').system('echo hacked')")

    def test_semicolon_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1;2")

    def test_eval_keyword_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("eval('1+1')")

    def test_quotes_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            calc("1+'2'")

    def test_source_has_no_eval(self) -> None:
        """Static check: no call to eval / exec / compile may appear anywhere in the source.

        This test is stronger than "a particular input cannot execute code" --
        it makes sure that anyone who adds eval to the code later trips the test
        immediately.

        One regular-expression pitfall:
          The first version was r"\\b(eval|exec|compile)\\s*\\(" and it also flagged
          `re.compile(r"...")` -- because re.compile does contain "compile(".
          The fix: require that these words are **not preceded by a dot**
          ((?<![.\\w])), which excludes `re.compile(` and `obj.exec(`, while a
          bare `compile(` / `eval(` is still caught.
        """
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "src"
        pattern = re.compile(r"(?<![.\w])(eval|exec|compile)\s*\(")
        offenders: list[str] = []

        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                # Skip comment lines: mentioning eval in a comment is allowed
                # (this project does so in several places)
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")

        self.assertEqual(
            offenders,
            [],
            "an eval/exec/compile call appears in the source: " + "; ".join(offenders),
        )


class TestExpressionPreserved(unittest.TestCase):
    """The outcome object must keep the expression entered by the user unchanged."""

    def test_expression_is_echoed(self) -> None:
        outcome = svc.calculate("12+8")
        self.assertEqual(outcome.expression, "12+8")
        self.assertEqual(outcome.result, "20")

    def test_expression_with_spaces_preserved(self) -> None:
        outcome = svc.calculate(" 1 + 2 ")
        self.assertEqual(outcome.expression, " 1 + 2 ")

    def test_value_is_decimal(self) -> None:
        outcome = svc.calculate("12+8")
        self.assertIsInstance(outcome.value, Decimal)

    def test_string_and_value_agree(self) -> None:
        outcome = svc.calculate("1.5+1.5")
        self.assertEqual(outcome.result, "3")
        self.assertEqual(outcome.value, Decimal(3))


class TestTryCalculate(unittest.TestCase):
    """The non-raising version."""

    def test_success_returns_outcome(self) -> None:
        outcome, error = svc.try_calculate("1+1")
        self.assertIsNotNone(outcome)
        self.assertIsNone(error)
        assert outcome is not None
        self.assertEqual(outcome.result, "2")

    def test_failure_returns_error(self) -> None:
        outcome, error = svc.try_calculate("1+")
        self.assertIsNone(outcome)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error.error_code, "INVALID_EXPRESSION")

    def test_division_by_zero_returns_error(self) -> None:
        outcome, error = svc.try_calculate("1/0")
        self.assertIsNone(outcome)
        assert error is not None
        self.assertEqual(error.error_code, "DIVISION_BY_ZERO")


if __name__ == "__main__":
    unittest.main()
