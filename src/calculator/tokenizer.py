"""词法分析器（tokenizer）—— 把一个表达式字符串切成一个个"记号"。

这个模块在整条计算链路里的位置：

    前端传来的字符串          "12+8"
        ↓  本模块
    记号序列                 [NUMBER(12), OP(+), NUMBER(8)]
        ↓  parser.py
    语法树（AST）             +(12, 8)
        ↓  evaluator.py
    计算结果                 20

为什么要有"词法分析"这一层，而不是直接解析字符串：
    把"切词"和"理解结构"分成两步，每一步都简单、都能单独测试。
    出问题时也好定位：是字符切错了，还是括号配对错了？

为什么不用 eval / exec：
    作业明确禁止把用户输入当代码执行。这里只是把字符串当**数据**来处理，
    即使输入 "1+__import__('os').system('rm -rf /')" 也只会被切成
    NUMBER(1) OP(+) 之后遇到非法字符而报错，永远不会被执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from src.common.errors import InvalidExpressionError


class TokenType(Enum):
    """记号的种类。

    只有三种：数字、运算符、括号。
    运算符里把一元负号也当作同一个符号，由解析器根据**位置**去区分它是
    二元减号还是一元负号（见 parser.py）。
    """

    NUMBER = "NUMBER"
    OPERATOR = "OPERATOR"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"


# 允许出现的运算符字符。其余字符一律视为非法输入。
OPERATOR_CHARS = "+-*/"
LPAREN_CHARS = "("
RPAREN_CHARS = ")"

# 允许作为数字一部分的字符
DIGIT_CHARS = "0123456789."
# 小数点最多出现几次（一个数字里只能有一次）
MAX_DOTS_PER_NUMBER = 1

# 表达式长度上限。防止超长输入（也防止有人用超长字符串试探解析器的极限）。
MAX_EXPRESSION_LENGTH = 200


@dataclass(frozen=True)
class Token:
    """一个记号。

    kind    记号种类
    value   记号内容。数字是 Decimal，运算符是单个字符
    pos     它在原字符串里的下标，报错时用来告诉用户"错在第几个字符"
    """

    kind: TokenType
    value: object
    pos: int

    def __repr__(self) -> str:  # 方便调试和测试输出
        return f"Token({self.kind.name}, {self.value!r}, pos={self.pos})"


def tokenize(expression: str) -> list[Token]:
    """把表达式字符串切成记号序列。

    Args:
        expression: 用户输入的表达式，例如 "1+2*3"

    Returns:
        记号列表。空白字符（空格、制表符）会被跳过，不计入记号。

    Raises:
        InvalidExpressionError: 表达式为空、超长，或含有非法字符、格式错误的数字
    """
    if expression is None:
        raise InvalidExpressionError("表达式不能为空")

    text = expression.strip()
    if text == "":
        raise InvalidExpressionError("表达式不能为空")

    if len(text) > MAX_EXPRESSION_LENGTH:
        raise InvalidExpressionError(
            f"表达式过长，最多 {MAX_EXPRESSION_LENGTH} 个字符"
        )

    tokens: list[Token] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # ---- 空白：跳过 ----
        if ch.isspace():
            i += 1
            continue

        # ---- 数字：连续的数字与小数点算一个记号 ----
        if ch in DIGIT_CHARS:
            start = i
            dots = 0
            while i < n and text[i] in DIGIT_CHARS:
                if text[i] == ".":
                    dots += 1
                    if dots > MAX_DOTS_PER_NUMBER:
                        raise InvalidExpressionError(
                            f"同一个数字里出现了多个小数点（第 {start + 1} 个字符起）"
                        )
                i += 1
            raw = text[start:i]
            tokens.append(Token(TokenType.NUMBER, _parse_number(raw, start), start))
            continue

        # ---- 运算符 ----
        if ch in OPERATOR_CHARS:
            tokens.append(Token(TokenType.OPERATOR, ch, i))
            i += 1
            continue

        # ---- 括号 ----
        if ch in LPAREN_CHARS:
            tokens.append(Token(TokenType.LPAREN, ch, i))
            i += 1
            continue
        if ch in RPAREN_CHARS:
            tokens.append(Token(TokenType.RPAREN, ch, i))
            i += 1
            continue

        # ---- 其余一律非法 ----
        # 包括字母、中文、全角符号等。前端虽然会拦住大部分，
        # 但接口是可以被直接调用的（比如用 curl），所以后端必须自己再查一遍。
        raise InvalidExpressionError(f"表达式中含有非法字符：{ch!r}（第 {i + 1} 个字符）")

    if not tokens:
        raise InvalidExpressionError("表达式不能为空")

    return tokens


def _parse_number(raw: str, pos: int) -> Decimal:
    """把一段数字文本转成 Decimal。

    为什么用 Decimal 而不是 float：
        float 是二进制浮点数，0.1 + 0.2 会得到 0.30000000000000004。
        计算器必须给出 0.3。Decimal 是十进制浮点，能精确表示 0.1 和 0.2。

    Args:
        raw: 数字文本，如 "12"、"3.5"，也可能是 "." 或 "1." 这种不完整形式
        pos: 它在原表达式里的下标（报错用）

    Returns:
        Decimal 对象

    Raises:
        InvalidExpressionError: 不是一个有效的数字
    """
    # 单独一个 "."、"1."、".5" 这三种情况要分别处理：
    #   "."    → 非法
    #   "1."   → 看作 1（写成 1.0 也合法）
    #   ".5"   → 看作 0.5
    if raw == ".":
        raise InvalidExpressionError(f"小数点前后缺少数字（第 {pos + 1} 个字符）")

    normalized = raw
    if normalized.startswith("."):
        normalized = "0" + normalized
    if normalized.endswith("."):
        normalized = normalized + "0"

    try:
        return Decimal(normalized)
    except InvalidOperation as exc:  # pragma: no cover - 正常路径不会走到
        raise InvalidExpressionError(f"无法识别的数字：{raw!r}") from exc
