"""Parser (syntax analysis) -- turns a token sequence into a syntax tree (AST).

This module implements operator precedence with **recursive descent**:
``_parse_expression`` handles only addition and subtraction, ``_parse_term``
handles only multiplication and division, and ``_parse_factor`` handles only
parentheses and unary plus/minus. Each level calls only the level below it, so
**precedence falls out of the call structure** and no precedence table is needed.

------------------------------------------------------------------
Where it sits in the calculation pipeline
------------------------------------------------------------------

    tokenizer.py  ->  [NUMBER(1), OP(+), NUMBER(2), OP(*), NUMBER(3)]
        |  this module
    syntax tree      BinaryOp(+, 1, BinaryOp(*, 2, 3))
        |  evaluator.py
    result           7           <- note 7, not 9: the multiplication runs first

------------------------------------------------------------------
Why there is a syntax tree layer at all
------------------------------------------------------------------

Could the tokens just be evaluated straight away? Yes, but then "what runs
first" would be buried in the code. The syntax tree **draws** precedence:

        +                <- the top node is evaluated last
       / \\
      1   *             <- multiplication sits below, so it runs first
         / \\
        2   3

The shape of the tree itself says "compute 2*3, then add 1". That makes the
evaluation step very simple: **post-order traversal** (children first, then the
node itself).

------------------------------------------------------------------
Grammar (recursive descent)
------------------------------------------------------------------

Recursive descent means "one function per precedence level", written from the
**lowest precedence** upwards:

    expression := term (("+" | "-") term)*      <- addition/subtraction (lowest precedence)
    term       := factor (("*" | "/") factor)*  <- multiplication/division (one level up)
    factor     := ("+" | "-") factor            <- unary plus/minus, e.g. -5, 3*-2
                | "(" expression ")"
                | NUMBER

Reading it: an expression is "several terms joined by + or -";
      a term is "several factors joined by * or /";
      a factor is "a signed factor", "a parenthesized expression", or "a number".

Why "one function per precedence level" is enough to get precedence right:
    Because expression calls term, and term calls factor.
    So when parsing "1+2*3", reaching the right-hand side of "+" calls term,
    and term swallows the whole "2*3" as one unit instead of taking just "2".
    **Who contains whom decides who is computed first.**

On unary minus: it is handled at the factor level, which is why it works
without any explicit "force precedence" step:
    "3*-2"  ->  term sees "*" and calls factor for the right side; factor sees
                "-" and returns UnaryOp(-, 2), so the term becomes
                BinaryOp(*, 3, -2).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Union

from src.calculator.tokenizer import Token, TokenType, tokenize
from src.common.errors import InvalidExpressionError


# ==================================================================
# Syntax tree node definitions
# ==================================================================


@dataclass(frozen=True)
class Number:
    """A number node."""

    value: Decimal


@dataclass(frozen=True)
class UnaryOp:
    """A unary operation node; currently only negation and unary plus.

    op       "+" or "-"
    operand  the child node the operator applies to
    """

    op: str
    operand: "Node"


@dataclass(frozen=True)
class BinaryOp:
    """A binary operation node.

    op     "+", "-", "*" or "/"
    left   left operand
    right  right operand
    """

    op: str
    left: "Node"
    right: "Node"


# Union of the syntax tree node types; used for typing only.
Node = Union[Number, UnaryOp, BinaryOp]


# ==================================================================
# Parser
# ==================================================================


class Parser:
    """Parse a token sequence into a syntax tree.

    It advances with a cursor plus a lookahead:
        self._pos     index of the token currently in view
        _peek()       look at the current token without consuming it
        _advance()    consume the current token and move one step forward
    """

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # --------------------------------------------------------------
    # Helper methods
    # --------------------------------------------------------------

    def _peek(self) -> Token | None:
        """Look at the current token without consuming it. Returns None at the end."""
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        """Consume the current token and move one step forward."""
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _is_operator(self, *chars: str) -> bool:
        """Whether the current token is one of the given operators.

        Example: self._is_operator("+", "-")
        """
        token = self._peek()
        return (
            token is not None
            and token.kind is TokenType.OPERATOR
            and token.value in chars
        )

    def _match_operator(self, *chars: str) -> str | None:
        """Consume and return the current token if it is one of these operators;
        otherwise return None.
        """
        if self._is_operator(*chars):
            return self._advance().value  # type: ignore[return-value]
        return None

    # --------------------------------------------------------------
    # Public entry point
    # --------------------------------------------------------------

    def parse(self) -> Node:
        """Parse the whole expression.

        **No other token may be left over** besides the expression itself --
        an extra closing parenthesis such as in "1+2)" has to be detected after
        the complete expression has been parsed.
        """
        node = self._parse_expression()

        leftover = self._peek()
        if leftover is not None:
            raise InvalidExpressionError(
                f"Extra content: {leftover.value!r} (character {leftover.pos + 1})"
            )

        return node

    # --------------------------------------------------------------
    # The next three are the core of this file
    # --------------------------------------------------------------

    def _parse_expression(self) -> Node:
        """Parse the addition/subtraction level. Grammar: expression := term (("+" | "-") term)*

        How it works (left associativity):
            1. Parse one term on the left.
            2. As long as a "+" or "-" follows, consume it, parse another term,
               and combine the result parsed so far as the **left subtree**.
            3. When the loop ends, the whole chain has been combined into a
               left-leaning tree.

        Why putting node on the left each round yields left associativity:
            "1-2-3" must be (1-2)-3 = -4, not 1-(2-3) = 2.
            Every round puts the part computed so far on the left, so the order
            is naturally left to right.

        Why this level has the lowest precedence:
            Because the _parse_term it calls swallows the whole
            multiplication/division chain as one term, so those are combined
            into a subtree first. Precedence comes from the call hierarchy
            rather than from a precedence table. The single criterion for this
            level is: _parse_expression must call _parse_term, never itself.
        """
        node = self._parse_term()

        # The walrus operator (:=) assigns inside the condition, saving the two
        # lines of "assign, then test". _match_operator returns None when it does
        # not match, so the loop condition works out naturally.
        while (op := self._match_operator("+", "-")) is not None:
            right = self._parse_term()
            node = BinaryOp(op, node, right)

        return node

    def _parse_term(self) -> Node:
        """Parse the multiplication/division level. Grammar: term := factor (("*" | "/") factor)*

        Structurally identical to _parse_expression, with two differences:
            1. It calls _parse_factor (not _parse_term).
            2. The operators it matches are "*" and "/".

        Never call _parse_expression here: that would put multiplication and
        division on the same level as addition and subtraction and precedence
        would be lost (1+2*3 would come out as 9 instead of 7).
        """
        node = self._parse_factor()

        while (op := self._match_operator("*", "/")) is not None:
            right = self._parse_factor()
            node = BinaryOp(op, node, right)

        return node

    def _parse_factor(self) -> Node:
        """Parse the "factor" level. Grammar:

            factor := ("+" | "-") factor     <- unary plus/minus
                    | "(" expression ")"     <- parentheses
                    | NUMBER                 <- number

        The recursion into itself is what allows repeated signs such as ``--5``.
        Parentheses recurse back up to ``_parse_expression``, which is what closes
        the loop between the lowest and the highest precedence level.
        """
        token = self._peek()
        if token is None:
            raise InvalidExpressionError("Missing a number or closing parenthesis at the end")

        # ---- Case 1: unary plus/minus ----
        # Note the **recursion** here: another "-" may follow a "-", so "--5" is legal too.
        if self._is_operator("+", "-"):
            op = self._advance().value
            operand = self._parse_factor()  # recursively parse the factor it applies to
            return UnaryOp(str(op), operand)

        # ---- Case 2: parentheses ----
        if token.kind is TokenType.LPAREN:
            self._advance()  # consume "("
            # a complete expression of its own inside the parentheses
            inner = self._parse_expression()
            closing = self._peek()
            if closing is None or closing.kind is not TokenType.RPAREN:
                raise InvalidExpressionError(
                    f"Unbalanced parentheses: the opening parenthesis at "
                    f"character {token.pos + 1} is unclosed"
                )
            self._advance()  # consume ")"
            return inner

        # ---- Case 3: number ----
        if token.kind is TokenType.NUMBER:
            self._advance()
            return Number(token.value)  # type: ignore[arg-type]

        # ---- Anything else: syntax error ----
        # For example "(1+)": after "1+" has been parsed inside the parentheses,
        # a factor is expected but ")" shows up
        if token.kind is TokenType.RPAREN:
            raise InvalidExpressionError(
                f"Missing a number or expression before the closing parenthesis "
                f"(character {token.pos + 1})"
            )
        raise InvalidExpressionError(
            f"Incomplete expression: {token.value!r} is in the wrong position "
            f"(character {token.pos + 1})"
        )


def parse(expression: str) -> Node:
    """Public API: string -> syntax tree.

    This is the only function other modules need to call (tokenize and Parser
    are internal details).

    Args:
        expression: the expression entered by the user

    Returns:
        The root node of the syntax tree

    Raises:
        InvalidExpressionError: the expression is not valid
    """
    tokens = tokenize(expression)
    return Parser(tokens).parse()
