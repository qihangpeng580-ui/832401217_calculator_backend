"""Tests: the tokenizer (lexical analysis).

Run (from the project root):
    py -3.12 -m unittest tests.test_tokenizer -v

Why the lowest layer, the tokenizer, is tested first:
    It is the first step of the whole pipeline. If tokenization is wrong, correct
    parsing and evaluation do not help, and the error points somewhere odd and is hard to trace.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.calculator.tokenizer import Token, TokenType, tokenize
from src.common.errors import InvalidExpressionError


def kinds(expression: str) -> list[str]:
    """Helper: look at the token kinds only, which keeps the assertions short."""
    return [t.kind.name for t in tokenize(expression)]


def values(expression: str) -> list[object]:
    """Helper: look at the token values only."""
    return [t.value for t in tokenize(expression)]


class TestTokenizeNumbers(unittest.TestCase):
    """Splitting numbers."""

    def test_single_digit(self) -> None:
        self.assertEqual(values("7"), [Decimal(7)])

    def test_multi_digit(self) -> None:
        self.assertEqual(values("123"), [Decimal(123)])

    def test_decimal(self) -> None:
        self.assertEqual(values("3.5"), [Decimal("3.5")])

    def test_leading_dot(self) -> None:
        """.5" counts as 0.5 (the front end pads a 0 too, but the API can be called directly)."""
        self.assertEqual(values(".5"), [Decimal("0.5")])

    def test_trailing_dot(self) -> None:
        """"1." counts as 1."""
        self.assertEqual(values("1."), [Decimal(1)])

    def test_zero(self) -> None:
        self.assertEqual(values("0"), [Decimal(0)])

    def test_multiple_dots_rejected(self) -> None:
        """Two decimal points in one number are illegal input."""
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1.2.3")
        self.assertIn("decimal points", str(ctx.exception))

    def test_lone_dot_rejected(self) -> None:
        """A lone "." is not a number."""
        with self.assertRaises(InvalidExpressionError):
            tokenize(".")


class TestTokenizeOperators(unittest.TestCase):
    """Operators and parentheses."""

    def test_all_operators(self) -> None:
        self.assertEqual(values("+-*/"), ["+", "-", "*", "/"])

    def test_parentheses(self) -> None:
        self.assertEqual(kinds("()"), ["LPAREN", "RPAREN"])

    def test_expression(self) -> None:
        self.assertEqual(
            kinds("12+8"),
            ["NUMBER", "OPERATOR", "NUMBER"],
        )

    def test_compound_expression(self) -> None:
        self.assertEqual(
            kinds("(1+2)*3"),
            ["LPAREN", "NUMBER", "OPERATOR", "NUMBER", "RPAREN", "OPERATOR", "NUMBER"],
        )

    def test_unary_minus_expression(self) -> None:
        """The minus in 3*-2 is the same token as subtraction;
        only its position tells them apart.
        """
        self.assertEqual(
            kinds("3*-2"),
            ["NUMBER", "OPERATOR", "OPERATOR", "NUMBER"],
        )


class TestTokenizeWhitespace(unittest.TestCase):
    """Whitespace must be skipped without affecting the position information."""

    def test_spaces_ignored(self) -> None:
        self.assertEqual(values(" 1 + 2 "), [Decimal(1), "+", Decimal(2)])

    def test_position_recorded(self) -> None:
        """A token's pos is its index in the original string and is used in error messages."""
        tokens = tokenize("1 + 2")
        self.assertEqual([t.pos for t in tokens], [0, 2, 4])

    def test_tabs_and_newlines(self) -> None:
        self.assertEqual(values("1\t+\n2"), [Decimal(1), "+", Decimal(2)])


class TestTokenizeInvalid(unittest.TestCase):
    """Illegal input."""

    def test_empty_string(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("")
        self.assertIn("cannot be empty", str(ctx.exception))

    def test_only_spaces(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("   ")

    def test_letters_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1+a")
        self.assertIn("Illegal character", str(ctx.exception))

    def test_chinese_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("1+二")

    def test_fullwidth_rejected(self) -> None:
        """The front end converts full-width symbols, but a direct API call must reject them."""
        with self.assertRaises(InvalidExpressionError):
            tokenize("1＋2")

    def test_semicolon_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("1;2")

    def test_code_injection_rejected(self) -> None:
        """Security test: parentheses and quotes must not become a way to execute code.

        The assignment forbids eval/exec. This checks that even when the user submits a
        string that "looks like code", it is only rejected as an illegal character.
        """
        dangerous = "__import__('os').system('ls')"
        with self.assertRaises(InvalidExpressionError):
            tokenize(dangerous)

    def test_too_long_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1" * 300)
        self.assertIn("too long", str(ctx.exception))


class TestTokenDataclass(unittest.TestCase):
    """The behaviour of Token itself."""

    def test_repr_readable(self) -> None:
        token = Token(TokenType.NUMBER, Decimal(7), 0)
        self.assertIn("NUMBER", repr(token))
        self.assertIn("7", repr(token))

    def test_frozen(self) -> None:
        """Token is immutable -- it must not change after tokenization."""
        token = Token(TokenType.NUMBER, Decimal(1), 0)
        with self.assertRaises(Exception):
            token.value = Decimal(2)  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
