"""测试：词法分析器（tokenizer）。

运行（在项目根目录下）：
    py -3.12 -m unittest tests.test_tokenizer -v

为什么先测最底层的 tokenizer：
    它是整条链路的第一步。如果切词就错了，后面解析和求值再对也没用，
    而且报错信息会指向一个奇怪的地方，很难查。
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.calculator.tokenizer import Token, TokenType, tokenize
from src.common.errors import InvalidExpressionError


def kinds(expression: str) -> list[str]:
    """辅助函数：只看记号的种类，方便断言。"""
    return [t.kind.name for t in tokenize(expression)]


def values(expression: str) -> list[object]:
    """辅助函数：只看记号的值。"""
    return [t.value for t in tokenize(expression)]


class TestTokenizeNumbers(unittest.TestCase):
    """数字的切分。"""

    def test_single_digit(self) -> None:
        self.assertEqual(values("7"), [Decimal(7)])

    def test_multi_digit(self) -> None:
        self.assertEqual(values("123"), [Decimal(123)])

    def test_decimal(self) -> None:
        self.assertEqual(values("3.5"), [Decimal("3.5")])

    def test_leading_dot(self) -> None:
        """".5" 应该被当成 0.5（前端也会自动补 0，但接口可能被直接调用）。"""
        self.assertEqual(values(".5"), [Decimal("0.5")])

    def test_trailing_dot(self) -> None:
        """"1." 应该被当成 1。"""
        self.assertEqual(values("1."), [Decimal(1)])

    def test_zero(self) -> None:
        self.assertEqual(values("0"), [Decimal(0)])

    def test_multiple_dots_rejected(self) -> None:
        """一个数字里两个小数点是非法输入。"""
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1.2.3")
        self.assertIn("小数点", str(ctx.exception))

    def test_lone_dot_rejected(self) -> None:
        """单独一个 "." 不是数字。"""
        with self.assertRaises(InvalidExpressionError):
            tokenize(".")


class TestTokenizeOperators(unittest.TestCase):
    """运算符与括号。"""

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
        """3*-2 里那个负号在词法阶段和减号是同一个记号，靠位置区分。"""
        self.assertEqual(
            kinds("3*-2"),
            ["NUMBER", "OPERATOR", "OPERATOR", "NUMBER"],
        )


class TestTokenizeWhitespace(unittest.TestCase):
    """空白字符应该被跳过，且不影响位置信息。"""

    def test_spaces_ignored(self) -> None:
        self.assertEqual(values(" 1 + 2 "), [Decimal(1), "+", Decimal(2)])

    def test_position_recorded(self) -> None:
        """记号的 pos 是它在原字符串里的下标，报错时要用。"""
        tokens = tokenize("1 + 2")
        self.assertEqual([t.pos for t in tokens], [0, 2, 4])

    def test_tabs_and_newlines(self) -> None:
        self.assertEqual(values("1\t+\n2"), [Decimal(1), "+", Decimal(2)])


class TestTokenizeInvalid(unittest.TestCase):
    """非法输入。"""

    def test_empty_string(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("")
        self.assertIn("不能为空", str(ctx.exception))

    def test_only_spaces(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("   ")

    def test_letters_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1+a")
        self.assertIn("非法字符", str(ctx.exception))

    def test_chinese_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("1+二")

    def test_fullwidth_rejected(self) -> None:
        """全角符号前端会转换，但接口直接调用时要拒绝。"""
        with self.assertRaises(InvalidExpressionError):
            tokenize("1＋2")

    def test_semicolon_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError):
            tokenize("1;2")

    def test_code_injection_rejected(self) -> None:
        """★ 安全测试：括号和引号不能被当成代码执行的入口。

        作业明确禁止 eval/exec。这里验证：即使用户输入一段"看起来像代码"的
        字符串，也只会被当成非法字符拒绝，绝不会有任何执行的机会。
        """
        dangerous = "__import__('os').system('ls')"
        with self.assertRaises(InvalidExpressionError):
            tokenize(dangerous)

    def test_too_long_rejected(self) -> None:
        with self.assertRaises(InvalidExpressionError) as ctx:
            tokenize("1" * 300)
        self.assertIn("过长", str(ctx.exception))


class TestTokenDataclass(unittest.TestCase):
    """Token 本身的行为。"""

    def test_repr_readable(self) -> None:
        token = Token(TokenType.NUMBER, Decimal(7), 0)
        self.assertIn("NUMBER", repr(token))
        self.assertIn("7", repr(token))

    def test_frozen(self) -> None:
        """Token 是不可变的 —— 切词之后不该再被改动。"""
        token = Token(TokenType.NUMBER, Decimal(1), 0)
        with self.assertRaises(Exception):
            token.value = Decimal(2)  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
