"""测试：语法分析器（parser）。

运行（在项目根目录下）：
    py -3.12 -m unittest tests.test_parser -v

★ 这个文件是给你实现 parser.py 时用的"验收标准"。
   一开始会有大批失败（因为 _parse_expression 和 _parse_term 还是 TODO），
   把这两个函数写完之后应该**全部通过**。

读懂断言的方法：断言写的是**语法树的形状**，不是计算结果。
比如 "1+2*3" 期望的形状是 BinaryOp(+, 1, BinaryOp(*, 2, 3)) ——
这正好证明了"乘法是加法的子树"，也就是"乘法先算"。
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.calculator.parser import BinaryOp, Node, Number, UnaryOp, parse
from src.common.errors import InvalidExpressionError


def tree(expression: str) -> Node:
    """辅助函数：解析一个表达式。"""
    return parse(expression)


def num(value: str) -> Number:
    """辅助函数：构造期望的 Number 节点，省得每次都写 Decimal()。"""
    return Number(Decimal(value))


class TestSimpleNumbers(unittest.TestCase):
    """最简单的输入。"""

    def test_single_number(self) -> None:
        self.assertEqual(tree("7"), num("7"))

    def test_decimal_number(self) -> None:
        self.assertEqual(tree("3.5"), num("3.5"))

    def test_spaces_ok(self) -> None:
        self.assertEqual(tree(" 7 "), num("7"))


class TestBinaryOperations(unittest.TestCase):
    """四则运算的树形状。"""

    def test_addition(self) -> None:
        self.assertEqual(tree("1+2"), BinaryOp("+", num("1"), num("2")))

    def test_subtraction(self) -> None:
        self.assertEqual(tree("9-4"), BinaryOp("-", num("9"), num("4")))

    def test_multiplication(self) -> None:
        self.assertEqual(tree("5*8"), BinaryOp("*", num("5"), num("8")))

    def test_division(self) -> None:
        self.assertEqual(tree("10/2"), BinaryOp("/", num("10"), num("2")))


class TestPrecedence(unittest.TestCase):
    """★ 优先级：乘除要成为加减的子树。

    这是 parser.py 里 _parse_expression 调 _parse_term 的直接结果。
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
        """1+2*3-4/2 应该解析成 ((1+(2*3))-(4/2))。"""
        self.assertEqual(
            tree("1+2*3-4/2"),
            BinaryOp(
                "-",
                BinaryOp("+", num("1"), BinaryOp("*", num("2"), num("3"))),
                BinaryOp("/", num("4"), num("2")),
            ),
        )


class TestLeftAssociativity(unittest.TestCase):
    """★ 左结合：同优先级的运算符从左往右算。

    "1-2-3" 必须是 (1-2)-3 = -4，不能是 1-(2-3) = 2。
    这一条由"循环里把已经算好的 node 当作左子树"保证。
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
        """100/5/2 应该是 (100/5)/2 = 10，不是 100/(5/2) = 40。"""
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
    """括号改变结合顺序。"""

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
    """★ 一元正负号。

    这一层在 _parse_factor 里处理（已写好），所以下面这些应该在
    _parse_expression 和 _parse_term 完成后就能通过。
    """

    def test_unary_minus(self) -> None:
        self.assertEqual(tree("-5"), UnaryOp("-", num("5")))

    def test_unary_plus(self) -> None:
        self.assertEqual(tree("+5"), UnaryOp("+", num("5")))

    def test_unary_minus_after_operator(self) -> None:
        """3*-2 —— 这是作业里点名要求支持的写法。"""
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
        """--5 应该是 -( -5 ) = 5。"""
        self.assertEqual(tree("--5"), UnaryOp("-", UnaryOp("-", num("5"))))

    def test_negative_in_parentheses(self) -> None:
        """(-5)+8 —— 作业示例之一。"""
        self.assertEqual(
            tree("(-5)+8"),
            BinaryOp("+", UnaryOp("-", num("5")), num("8")),
        )

    def test_frontend_style_negative(self) -> None:
        """前端按 ± 时产生的是 (-3) 这种形式。"""
        self.assertEqual(
            tree("5+(-3)"),
            BinaryOp("+", num("5"), UnaryOp("-", num("3"))),
        )


class TestInvalidExpressions(unittest.TestCase):
    """★ 非法表达式必须报错，而不是"尽量猜"。

    这些是最容易被漏掉的边界情况。
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
        """* 不能做一元运算符。"""
        with self.assertRaises(InvalidExpressionError):
            tree("*5")

    def test_unclosed_parenthesis(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tree("(1+2")
        self.assertIn("括号", str(ctx.exception))

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
        """1++2 里的第二个 + 会被当成一元加号，所以这个**是合法的**。

        前端不会产生这种输入（连续运算符会被替换），
        但接口可能被直接调用，所以后端要能处理。
        """
        node = tree("1++2")
        self.assertEqual(node, BinaryOp("+", num("1"), UnaryOp("+", num("2"))))

    def test_two_binary_operators_invalid(self) -> None:
        """1+*2 里 * 不能做一元运算符，必须报错。"""
        with self.assertRaises(InvalidExpressionError):
            tree("1+*2")


if __name__ == "__main__":
    unittest.main()
