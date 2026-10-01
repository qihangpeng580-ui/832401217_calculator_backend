"""Tests: the parser (syntax analysis).

Run (from the project root):
    py -3.12 -m unittest tests.test_parser -v

This file covers precedence, associativity, parentheses, unary plus/minus, and
the error messages produced for the various syntax errors.

How to read the assertions: they describe the **shape of the syntax tree**, not
the computed value. For example "1+2*3" is expected to be
BinaryOp(+, 1, BinaryOp(*, 2, 3)) -- which is exactly the proof that
"multiplication is a subtree of addition", that is, that multiplication is
computed first.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.calculator.parser import BinaryOp, Node, Number, UnaryOp, parse
from src.common.errors import InvalidExpressionError


def tree(expression: str) -> Node:
    """Helper: parse an expression."""
    return parse(expression)


def num(value: str) -> Number:
    """Helper: build the expected Number node, so Decimal() need not be written every time."""
    return Number(Decimal(value))


class TestSimpleNumbers(unittest.TestCase):
    """The simplest input."""

    def test_single_number(self) -> None:
        self.assertEqual(tree("7"), num("7"))

    def test_decimal_number(self) -> None:
        self.assertEqual(tree("3.5"), num("3.5"))

    def test_spaces_ok(self) -> None:
        self.assertEqual(tree(" 7 "), num("7"))


class TestBinaryOperations(unittest.TestCase):
    """Tree shapes for the four arithmetic operations."""

    def test_addition(self) -> None:
        self.assertEqual(tree("1+2"), BinaryOp("+", num("1"), num("2")))

    def test_subtraction(self) -> None:
        self.assertEqual(tree("9-4"), BinaryOp("-", num("9"), num("4")))

    def test_multiplication(self) -> None:
        self.assertEqual(tree("5*8"), BinaryOp("*", num("5"), num("8")))

    def test_division(self) -> None:
        self.assertEqual(tree("10/2"), BinaryOp("/", num("10"), num("2")))


class TestPrecedence(unittest.TestCase):
    """Precedence: multiplication and division must become subtrees of addition and subtraction.

    This follows directly from _parse_expression calling _parse_term in parser.py.
    """

    def test_multiplication_binds_tighter(self) -> None:
        self.assertEqual(
            tree("1+2*3"),
            BinaryOp("+", num("1"), BinaryOp("*", num("2"), num("3"))),
        )

    def test_division_binds_tighter(self) -> None:
        self.assertEqual(
            tree("10/2+7"),
            BinaryOp("+", BinaryOp("/", num("10"), num("2")), num("7")),
        )

    def test_subtraction_and_multiplication(self) -> None:
        self.assertEqual(
            tree("8-3*2"),
            BinaryOp("-", num("8"), BinaryOp("*", num("3"), num("2"))),
        )

    def test_all_four_operators(self) -> None:
        """1+2*3-4/2 should parse as ((1+(2*3))-(4/2))."""
        self.assertEqual(
            tree("1+2*3-4/2"),
            BinaryOp(
                "-",
                BinaryOp("+", num("1"), BinaryOp("*", num("2"), num("3"))),
                BinaryOp("/", num("4"), num("2")),
            ),
        )


class TestLeftAssociativity(unittest.TestCase):
    """Left associativity: operators of equal precedence are computed left to right.

    "1-2-3" must be (1-2)-3 = -4, never 1-(2-3) = 2.
    That is guaranteed by using the node computed so far as the left subtree in the loop.
    """

    def test_subtraction_is_left_associative(self) -> None:
        self.assertEqual(
            tree("1-2-3"),
            BinaryOp("-", BinaryOp("-", num("1"), num("2")), num("3")),
        )

    def test_addition_is_left_associative(self) -> None:
        self.assertEqual(
            tree("1+2+3"),
            BinaryOp("+", BinaryOp("+", num("1"), num("2")), num("3")),
        )

    def test_division_is_left_associative(self) -> None:
        """100/5/2 should be (100/5)/2 = 10, not 100/(5/2) = 40."""
        self.assertEqual(
            tree("100/5/2"),
            BinaryOp("/", BinaryOp("/", num("100"), num("5")), num("2")),
        )

    def test_mixed_same_precedence(self) -> None:
        self.assertEqual(
            tree("1+2-3"),
            BinaryOp("-", BinaryOp("+", num("1"), num("2")), num("3")),
        )


class TestParentheses(unittest.TestCase):
    """Parentheses change the grouping."""

    def test_parentheses_override_precedence(self) -> None:
        self.assertEqual(
            tree("(1+2)*3"),
            BinaryOp("*", BinaryOp("+", num("1"), num("2")), num("3")),
        )

    def test_nested_parentheses(self) -> None:
        self.assertEqual(
            tree("((1+2))*3"),
            BinaryOp("*", BinaryOp("+", num("1"), num("2")), num("3")),
        )

    def test_parentheses_around_number(self) -> None:
        self.assertEqual(tree("(5)"), num("5"))

    def test_complex_nesting(self) -> None:
        self.assertEqual(
            tree("2*(3+(4-1))"),
            BinaryOp(
                "*",
                num("2"),
                BinaryOp("+", num("3"), BinaryOp("-", num("4"), num("1"))),
            ),
        )


class TestUnaryOperators(unittest.TestCase):
    """Unary plus and minus.

    This level is handled inside _parse_factor (already written), so once
    _parse_expression and _parse_term are done these cases should pass.
    """

    def test_unary_minus(self) -> None:
        self.assertEqual(tree("-5"), UnaryOp("-", num("5")))

    def test_unary_plus(self) -> None:
        self.assertEqual(tree("+5"), UnaryOp("+", num("5")))

    def test_unary_minus_after_operator(self) -> None:
        """3*-2 -- the assignment explicitly calls for this form to be supported."""
        self.assertEqual(
            tree("3*-2"),
            BinaryOp("*", num("3"), UnaryOp("-", num("2"))),
        )

    def test_unary_plus_after_operator(self) -> None:
        self.assertEqual(
            tree("3*+2"),
            BinaryOp("*", num("3"), UnaryOp("+", num("2"))),
        )

    def test_unary_minus_before_parenthesis(self) -> None:
        self.assertEqual(
            tree("-(1+2)"),
            UnaryOp("-", BinaryOp("+", num("1"), num("2"))),
        )

    def test_double_negative(self) -> None:
        """--5 should be -( -5 ) = 5."""
        self.assertEqual(tree("--5"), UnaryOp("-", UnaryOp("-", num("5"))))

    def test_negative_in_parentheses(self) -> None:
        """(-5)+8 -- one of the assignment examples."""
        self.assertEqual(
            tree("(-5)+8"),
            BinaryOp("+", UnaryOp("-", num("5")), num("8")),
        )

    def test_frontend_style_negative(self) -> None:
        """The front-end's +/- key produces forms such as (-3)."""
        self.assertEqual(
            tree("5+(-3)"),
            BinaryOp("+", num("5"), UnaryOp("-", num("3"))),
        )


class TestInvalidExpressions(unittest.TestCase):
    """Invalid expressions must raise an error instead of being "guessed at".

    These are the edge cases most easily missed.
    """

    def test_empty(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("")

    def test_only_operator(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("+")

    def test_trailing_operator(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("1+")

    def test_trailing_operator_complex(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("1+2*")

    def test_leading_binary_operator(self) -> None:
        """* cannot act as a unary operator."""
        with self.assertRaises(InvalidExpressionError):
            tree("*5")

    def test_unclosed_parenthesis(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tree("(1+2")
        self.assertIn("parentheses", str(ctx.exception))

    def test_extra_closing_parenthesis(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("1+2)")

    def test_empty_parentheses(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("()")

    def test_operator_only_inside_parentheses(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tree("(1+)")

    def test_two_operators_in_a_row(self) -> None:
        """The second + in 1++2 is treated as a unary plus, so this **is legal**.

        The front-end never produces such input (consecutive operators are
        replaced), but the API can be called directly, so the back-end has to
        handle it.
        """
        node = tree("1++2")
        self.assertEqual(node, BinaryOp("+", num("1"), UnaryOp("+", num("2"))))

    def test_two_binary_operators_invalid(self) -> None:
        """In 1+*2 the * cannot be a unary operator and must raise an error."""
        with self.assertRaises(InvalidExpressionError):
            tree("1+*2")


if __name__ == "__main__":
    unittest.main()
