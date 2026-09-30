"""Evaluator -- walks the syntax tree and produces the result.

This is the end of the calculation pipeline and the **only place that actually
does arithmetic**.

Where it sits in the pipeline:

    tokenizer.py  ->  tokens
        |
    parser.py     ->  syntax tree
        |  this module
    result (Decimal)

------------------------------------------------------------------
The core idea: post-order traversal
------------------------------------------------------------------

The syntax tree has already "drawn" precedence (multiplication sits lower), so
evaluation needs only one rule:

    **Evaluate the children first, then the node itself.**

Take "1+2*3"; the tree looks like this:

        +(1, *(2,3))
        /  \\
       1    *(2,3)
            /  \\
           2    3

Evaluation order:
    1. To compute the top-level + we first need the values of its two children.
    2. The left child is 1 -> the value is 1.
    3. The right child is *(2,3) -> it has to be computed first: 2*3 = 6.
    4. Now both children are known -> 1 + 6 = 7.

Note that **no line in the evaluator tests precedence**. Precedence is decided
entirely by the shape of the tree. That is the payoff of "put the complexity in
the parsing stage so the evaluation stage stays simple".
"""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

from src.calculator.parser import BinaryOp, Node, Number, UnaryOp
from src.common.errors import DivisionByZeroError

# Arithmetic precision for Decimal. 28 digits is more than enough for a calculator.
# The value is set so that a non-terminating division such as "1/3" does not
# produce an extremely long decimal.
PRECISION = 28

# Maximum number of decimal places kept in a result. Anything beyond is rounded.
MAX_RESULT_SCALE = 12


def evaluate(node: Node) -> Decimal:
    """Evaluate a syntax tree.

    Args:
        node: the root node of the syntax tree

    Returns:
        The result as a Decimal

    Raises:
        DivisionByZeroError: the divisor is zero
        InvalidExpressionError: the result is outside the representable range
    """
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return _eval(node)


def _eval(node: Node) -> Decimal:
    """Recursive evaluation. Dispatches on the node type."""
    # ---- Number node: return the value directly ----
    if isinstance(node, Number):
        return node.value

    # ---- Unary operation: evaluate the operand first, then decide about negation ----
    if isinstance(node, UnaryOp):
        value = _eval(node.operand)
        if node.op == "-":
            return -value
        # Unary "+" leaves the value unchanged; it is written out so that the
        # code covers this case explicitly
        return value

    # ---- Binary operation: evaluate both children, then apply the operator ----
    if isinstance(node, BinaryOp):
        left = _eval(node.left)
        right = _eval(node.right)

        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            # The division-by-zero check must happen here, and before the division.
            #   A plain left / right would make Decimal raise decimal.DivisionByZero,
            #   which is a "library error": the front-end would never see the
            #   DIVISION_BY_ZERO error code we agreed on.
            if right == 0:
                raise DivisionByZeroError("Division by zero is not allowed")
            return left / right

        # Unreachable in theory (the parser only produces these four operators)
        raise AssertionError(f"Unknown operator: {node.op}")  # pragma: no cover

    raise AssertionError(f"Unknown node type: {type(node).__name__}")  # pragma: no cover


def format_result(value: Decimal) -> str:
    """Turn a Decimal result into a string suitable for display and storage.

    Three things need to happen:
        1. Drop redundant trailing integer zeros: Decimal("20.00") -> "20"
        2. Drop trailing zeros in the fraction:   Decimal("3.50")  -> "3.5"
        3. Avoid scientific notation:             Decimal("1E+1")   -> "10"
           (some Decimal operations return scientific notation and a plain
             str() would give "1E+1", which looks odd on screen)

    Args:
        value: the calculation result

    Returns:
        The normalized string

    Raises:
        InvalidExpressionError: the result is not finite (should not happen in practice)
    """
    if not value.is_finite():
        from src.common.errors import InvalidExpressionError

        raise InvalidExpressionError("The result is outside the representable range")

    # quantize caps the number of decimal places at MAX_RESULT_SCALE and rounds the rest
    try:
        with localcontext() as ctx:
            ctx.prec = PRECISION
            quantized = value.quantize(Decimal(1).scaleb(-MAX_RESULT_SCALE))
    except InvalidOperation:  # pragma: no cover - only triggered by extreme values
        quantized = value

    # normalize() strips trailing zeros but can also turn 100 into 1E+2, so the code
    # below handles that
    normalized = quantized.normalize()

    # format(..., "f") forces fixed-point notation and avoids scientific notation
    text = format(normalized, "f")

    # "20.000000" -> "20"; forms such as ".5" need a leading zero
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-"):
        text = "0"
    if text.startswith("."):
        text = "0" + text
    if text.startswith("-."):
        text = "-0" + text[1:]

    return text
