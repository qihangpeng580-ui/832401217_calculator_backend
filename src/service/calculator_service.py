"""计算服务 —— 把"词法分析 → 语法分析 → 求值"串成一条流水线。

这一层很薄，几乎只有编排。它的价值在于：

    1. **对外只暴露一个方法** ``calculate(expression)``，
       调用方（HTTP 层、测试、命令行）都不需要知道内部有三步。
    2. **所有异常都在这里统一转换**：底层抛的是 InvalidExpressionError 等业务异常，
       这一层保证它们带着统一的形状往上冒，HTTP 层只需要捕获 CalcError。
    3. **结果格式化的唯一入口**：无论是返回给前端还是写进数据库，
       都经过 ``format_result``，保证 "20" 不会一处是 "20.0" 另一处是 "20"。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.calculator.evaluator import evaluate, format_result
from src.calculator.parser import parse
from src.common.errors import CalcError, InvalidExpressionError


@dataclass(frozen=True)
class CalculationOutcome:
    """一次计算的完整结果。

    expression  用户输入的原始表达式（原样保留，不规范化）
    result      计算结果，用规范化后的**字符串**表示
    value       同一个结果的数值形式（给 API 返回 JSON 数字用）
    """

    expression: str
    result: str
    value: Decimal


class CalculatorService:
    """计算服务。

    无状态：同一个实例可以被多个请求共用，不需要每次新建。
    （当前的实现里它确实没有任何实例属性，这样在 HTTP 多线程环境下也不用加锁。）
    """

    def calculate(self, expression: str) -> CalculationOutcome:
        """计算一个表达式。

        Args:
            expression: 用户输入的表达式，例如 "1+2*3"

        Returns:
            CalculationOutcome

        Raises:
            InvalidExpressionError: 表达式不合法（语法错、非法字符、括号不匹配）
            DivisionByZeroError: 除数为零
        """
        if not isinstance(expression, str):
            raise InvalidExpressionError("表达式必须是字符串")

        # 第一步：切词（tokenizer.py）
        # 第二步：建语法树（parser.py）
        # 第三步：求值（evaluator.py）
        #
        # 三步依次写开，而不是链成一行 parse(expression) 之后再 evaluate，
        # 是为了将来在某一步中间插入日志或缓存时不用改结构。
        tree = parse(expression)
        raw_value = evaluate(tree)
        text = format_result(raw_value)

        return CalculationOutcome(
            expression=expression,
            result=text,
            value=raw_value,
        )

    def try_calculate(self, expression: str) -> tuple[CalculationOutcome | None, CalcError | None]:
        """calculate 的"不抛异常"版本，返回 (结果, 错误) 二元组。

        为什么提供两个版本：
            HTTP 层用 try_calculate 可以少写一层 try/except，读起来更平；
            测试层用 calculate 可以直接断言异常类型，更直观。
            两个都保留，各自用在合适的地方。

        Returns:
            (结果, None) 或 (None, 错误)
        """
        try:
            return self.calculate(expression), None
        except CalcError as exc:
            return None, exc
