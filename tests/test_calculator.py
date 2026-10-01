"""测试：完整的计算链路（词法 → 语法 → 求值 → 格式化）。

运行（在项目根目录下）：
    py -3.12 -m unittest tests.test_calculator -v

★ 这是最像"作业验收"的一组测试：
   开头的几组用例直接抄自作业帖里给出的示例表达式。

和 test_parser.py 的分工：
    test_parser.py  只检查**语法树的形状**（左边结合、优先级对不对）
    本文件          检查**最终算出来的数**对不对
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.common.errors import DivisionByZeroError, InvalidExpressionError
from src.service.calculator_service import CalculatorService

svc = CalculatorService()


def calc(expression: str) -> str:
    """辅助函数：算一个表达式，返回字符串结果。"""
    return svc.calculate(expression).result


class TestAssignmentExamples(unittest.TestCase):
    """★ 作业帖里逐字给出的示例表达式。

    原文（Part 1 功能 1 与功能 2）：
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
        """作业示例是带空格的写法，后端要能吃下空格。"""
        self.assertEqual(calc("1 + 2 * 3"), "7")
        self.assertEqual(calc("( 1 + 2 ) * 3"), "9")


class TestFourOperations(unittest.TestCase):
    """四则运算的基本正确性。"""

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
    """小数 —— 这里要证明用 Decimal 而不是 float 的价值。"""

    def test_decimal_addition(self) -> None:
        """★ 这是选 Decimal 的直接理由。

        用 float 算 0.1+0.2 会得到 0.30000000000000004；
        计算器必须给出 0.3，否则用户一看就知道是坏的。
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
        """除不尽的情况：保留有限位小数，不能显示一长串。"""
        result = calc("1/3")
        self.assertTrue(result.startswith("0.333333"))
        self.assertLessEqual(len(result), 15)

    def test_trailing_zeros_removed(self) -> None:
        """20.00 要显示成 20 而不是 20.00。"""
        self.assertEqual(calc("10.00*2"), "20")

    def test_leading_dot(self) -> None:
        self.assertEqual(calc(".5+.5"), "1")

    def test_trailing_dot(self) -> None:
        self.assertEqual(calc("1.+1"), "2")


class TestPrecedenceAndParentheses(unittest.TestCase):
    """优先级与括号。"""

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
        """1-2-3 = -4（从左往右），不是 1-(2-3) = 2。"""
        self.assertEqual(calc("1-2-3"), "-4")

    def test_left_associativity_division(self) -> None:
        """100/5/2 = 10，不是 100/(5/2) = 40。"""
        self.assertEqual(calc("100/5/2"), "10")

    def test_complex_expression(self) -> None:
        self.assertEqual(calc("((1+2)*(3+4))-5"), "16")


class TestUnaryOperators(unittest.TestCase):
    """一元正负号。"""

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
        """前端按 ± 产生的是 (-3) 这种形式，后端要能算。"""
        self.assertEqual(calc("5+(-3)"), "2")
        self.assertEqual(calc("5*(-3)"), "-15")


class TestDivisionByZero(unittest.TestCase):
    """★ 除零必须给出约定的错误，而不是让 Decimal 抛库异常。

    前端 ui.js 里有一张错误码表，`DIVISION_BY_ZERO` 对应中文「除数不能为 0」。
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
        """除数是算出来等于 0 的表达式，也要拦住。"""
        with self.assertRaises(DivisionByZeroError):
            calc("10/(5-5)")

    def test_division_by_zero_inside_expression(self) -> None:
        with self.assertRaises(DivisionByZeroError):
            calc("1+2/0")

    def test_zero_divided_by_something_is_fine(self) -> None:
        """0 做被除数没问题。"""
        self.assertEqual(calc("0/5"), "0")


class TestInvalidExpressions(unittest.TestCase):
    """非法表达式 —— 作业要求「Invalid expression handling」。"""

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
    """★ 安全：绝不能把用户输入当代码执行。

    作业明确禁止 eval/exec。这一组测试是从"攻击者视角"写的：
    即使用户把一段 Python 代码当表达式提交，也只会得到"非法字符"，不会有任何执行。
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
        """静态检查：整份源码里不允许出现 eval / exec / compile 的调用。

        这条测试比"某个输入不能执行"更强 ——
        它保证以后有人往代码里加 eval 时会立刻被测试发现。

        ★ 关于正则的一个坑（自己踩过）：
          一开始写成 r"\\b(eval|exec|compile)\\s*\\("，结果把
          `re.compile(r"...")` 也报成了违规 —— 因为 re.compile 里确实含 "compile("。
          修法：要求这些词**前面不是点号**（(?<![.\\w])），
          这样 `re.compile(` 与 `obj.exec(` 就会被排除，
          而光秃秃的 `compile(` / `eval(` 仍会被抓住。
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
                # 跳过注释行：注释里提到 eval 是允许的（本项目就多处说明"不用 eval"）
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")

        self.assertEqual(offenders, [], "源码里出现了 eval/exec/compile 调用：" + "; ".join(offenders))


class TestExpressionPreserved(unittest.TestCase):
    """结果对象里要原样保留用户输入的表达式。"""

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
    """不抛异常的版本。"""

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
