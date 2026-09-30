"""Tokenizer (lexical analysis) -- splits an expression string into individual "tokens".

Where this module sits in the calculation pipeline:

    string from the front-end   "12+8"
        |  this module
    token sequence              [NUMBER(12), OP(+), NUMBER(8)]
        |  parser.py
    syntax tree (AST)           +(12, 8)
        |  evaluator.py
    result                      20

Why have a separate tokenization step instead of parsing the string directly:
    Splitting the text and understanding its structure become two jobs, each of
    them simple and testable on its own. It also makes failures easier to place:
    was a character split wrongly, or were parentheses not matched?

Why not eval / exec:
    The assignment explicitly forbids executing user input as code. Here the
    string is only ever treated as **data**: even the input
    "1+__import__('os').system('rm -rf /')" is merely split into
    NUMBER(1) OP(+) and then rejected on the first illegal character. It is
    never executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from src.common.errors import InvalidExpressionError


class TokenType(Enum):
    """The kind of a token.

    There are only three kinds: number, operator and parenthesis.
    Unary minus uses the same operator symbol; the parser decides from the
    token's **position** whether it is a binary minus or a unary minus
    (see parser.py).
    """

    NUMBER = "NUMBER"
    OPERATOR = "OPERATOR"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"


# Operator characters that are allowed. Every other character is illegal input.
OPERATOR_CHARS = "+-*/"
LPAREN_CHARS = "("
RPAREN_CHARS = ")"

# Characters that may be part of a number
DIGIT_CHARS = "0123456789."
# Maximum number of decimal points (a number may contain only one)
MAX_DOTS_PER_NUMBER = 1

# Expression length limit. Guards against oversized input (and against anyone
# probing the parser's limits with a huge string).
MAX_EXPRESSION_LENGTH = 200


@dataclass(frozen=True)
class Token:
    """A single token.

    kind    the kind of the token
    value   the token content: a Decimal for numbers, a single character for operators
    pos     its index in the original string, used in error messages to tell the
            user which character is wrong
    """

    kind: TokenType
    value: object
    pos: int

    def __repr__(self) -> str:  # handy for debugging and test output
        return f"Token({self.kind.name}, {self.value!r}, pos={self.pos})"


def tokenize(expression: str) -> list[Token]:
    """Split an expression string into a sequence of tokens.

    Args:
        expression: the expression entered by the user, for example "1+2*3"

    Returns:
        The token list. Whitespace (spaces, tabs) is skipped and produces no token.

    Raises:
        InvalidExpressionError: the expression is empty, too long, or contains an
            illegal character or a malformed number
    """
    if expression is None:
        raise InvalidExpressionError("Expression cannot be empty")

    text = expression.strip()
    if text == "":
        raise InvalidExpressionError("Expression cannot be empty")

    if len(text) > MAX_EXPRESSION_LENGTH:
        raise InvalidExpressionError(
            f"Expression is too long, at most {MAX_EXPRESSION_LENGTH} characters"
        )

    tokens: list[Token] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # ---- Whitespace: skip ----
        if ch.isspace():
            i += 1
            continue

        # ---- Number: consecutive digits and decimal points form one token ----
        if ch in DIGIT_CHARS:
            start = i
            dots = 0
            while i < n and text[i] in DIGIT_CHARS:
                if text[i] == ".":
                    dots += 1
                    if dots > MAX_DOTS_PER_NUMBER:
                        raise InvalidExpressionError(
                            f"Multiple decimal points in the same number "
                            f"(from character {start + 1})"
                        )
                i += 1
            raw = text[start:i]
            tokens.append(Token(TokenType.NUMBER, _parse_number(raw, start), start))
            continue

        # ---- Operator ----
        if ch in OPERATOR_CHARS:
            tokens.append(Token(TokenType.OPERATOR, ch, i))
            i += 1
            continue

        # ---- Parenthesis ----
        if ch in LPAREN_CHARS:
            tokens.append(Token(TokenType.LPAREN, ch, i))
            i += 1
            continue
        if ch in RPAREN_CHARS:
            tokens.append(Token(TokenType.RPAREN, ch, i))
            i += 1
            continue

        # ---- Anything else is illegal ----
        # Letters, Chinese characters, full-width symbols and so on. The front-end
        # blocks most of them, but the API can be called directly (with curl, say),
        # so the back-end has to validate again on its own.
        raise InvalidExpressionError(
            f"Illegal character {ch!r} in the expression "
            f"(character {i + 1})"
        )

    if not tokens:
        raise InvalidExpressionError("Expression cannot be empty")

    return tokens


def _parse_number(raw: str, pos: int) -> Decimal:
    """Convert a piece of numeric text into a Decimal.

    Why Decimal instead of float:
        float is a binary floating-point type, so 0.1 + 0.2 yields
        0.30000000000000004, while a calculator must show 0.3. Decimal is a
        decimal floating-point type and represents 0.1 and 0.2 exactly.

    Args:
        raw: the numeric text, such as "12" or "3.5"; it may also be an incomplete
            form such as "." or "1."
        pos: its index in the original expression (used for error messages)

    Returns:
        A Decimal object

    Raises:
        InvalidExpressionError: not a valid number
    """
    # The three cases ".", "1." and ".5" each need their own handling:
    #   "."    -> illegal
    #   "1."   -> treated as 1 (writing 1.0 is legal too)
    #   ".5"   -> treated as 0.5
    if raw == ".":
        raise InvalidExpressionError(f"Missing digits at the decimal point (character {pos + 1})")

    normalized = raw
    if normalized.startswith("."):
        normalized = "0" + normalized
    if normalized.endswith("."):
        normalized = normalized + "0"

    try:
        return Decimal(normalized)
    except InvalidOperation as exc:  # pragma: no cover - never reached on the normal path
        raise InvalidExpressionError(f"Unrecognized number: {raw!r}") from exc
