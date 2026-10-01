"""求值器（evaluator）—— 遍历语法树，算出结果。

这一步是整个计算链路的终点，也是**唯一真正做算术的地方**。

它在链路里的位置：

    tokenizer.py  →  记号
        ↓
    parser.py     →  语法树
        ↓  本模块
    结果（Decimal）

------------------------------------------------------------------
核心：后序遍历
------------------------------------------------------------------

语法树已经把优先级"画"出来了（乘法在更下层），所以求值只需要一句规则：

    **先算孩子，再算自己。**

拿 "1+2*3" 举例，树是这样：

        +(1, *(2,3))
        /  \\
       1    *(2,3)
            /  \\
           2    3

求值顺序：
    1. 要算最上面的 +，先得知道它两个孩子是多少
    2. 左孩子是 1 → 直接得到 1
    3. 右孩子是 *(2,3) → 得先算它：2*3 = 6
    4. 现在两个孩子的值都有了 → 1 + 6 = 7

注意：**求值器里没有一行代码在判断优先级**。优先级完全由树的结构决定。
这就是"把复杂度放在解析阶段，让求值阶段变简单"的收益。
"""

from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

from src.calculator.parser import BinaryOp, Node, Number, UnaryOp
from src.common.errors import DivisionByZeroError

# Decimal 的运算精度。28 位对计算器来说绰绰有余。
# 定这个值是为了避免 "1/3" 这种除不尽的情况产生超长小数。
PRECISION = 28

# 结果里最多保留多少位小数。超过就四舍五入。
MAX_RESULT_SCALE = 12


def evaluate(node: Node) -> Decimal:
    """计算语法树的值。

    Args:
        node: 语法树的根节点

    Returns:
        Decimal 类型的结果

    Raises:
        DivisionByZeroError: 除数为零
        InvalidExpressionError: 运算结果超出可表示范围
    """
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return _eval(node)


def _eval(node: Node) -> Decimal:
    """递归求值。按节点类型分派。"""
    # ---- 数字节点：直接返回 ----
    if isinstance(node, Number):
        return node.value

    # ---- 一元运算：先算被作用的那个，再决定要不要取负 ----
    if isinstance(node, UnaryOp):
        value = _eval(node.operand)
        if node.op == "-":
            return -value
        # 一元 "+" 不改变值，写出来是为了让代码显式覆盖这种情况
        return value

    # ---- 二元运算：先算两个孩子，再按运算符计算 ----
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
            # ★ 除零检查必须在这里做，而且要在做除法之前做。
            #   如果直接 left / right，Decimal 会抛 decimal.DivisionByZero，
            #   那是"库的错误"，前端拿不到我们约定的 DIVISION_BY_ZERO 错误码。
            if right == 0:
                raise DivisionByZeroError("除数不能为 0")
            return left / right

        # 理论上不会走到这里（解析器只产生这四种运算符）
        raise AssertionError(f"未知的运算符：{node.op}")  # pragma: no cover

    raise AssertionError(f"未知的节点类型：{type(node).__name__}")  # pragma: no cover


def format_result(value: Decimal) -> str:
    """把 Decimal 结果整理成适合显示和存储的字符串。

    要做三件事：
        1. 去掉多余的尾零：Decimal("20.00") → "20"
        2. 去掉小数尾部的零：Decimal("3.50")  → "3.5"
        3. 避免科学计数法：Decimal("1E+1")    → "10"
           （Decimal 在某些运算后会给出科学计数法形式，直接 str() 会得到 "1E+1"，
             显示出来很奇怪）

    Args:
        value: 计算结果

    Returns:
        规范化后的字符串

    Raises:
        InvalidExpressionError: 结果不是有限数（理论上不会发生）
    """
    if not value.is_finite():
        from src.common.errors import InvalidExpressionError

        raise InvalidExpressionError("计算结果超出了可表示的范围")

    # quantize 把小数位数限制在 MAX_RESULT_SCALE 之内，超出部分四舍五入
    try:
        with localcontext() as ctx:
            ctx.prec = PRECISION
            quantized = value.quantize(Decimal(1).scaleb(-MAX_RESULT_SCALE))
    except InvalidOperation:  # pragma: no cover - 极端大数才会触发
        quantized = value

    # normalize() 会去掉尾零，但也可能把 100 变成 1E+2，所以下面还要处理
    normalized = quantized.normalize()

    # 用 format(..., "f") 强制定点表示，避免科学计数法
    text = format(normalized, "f")

    # "20.000000" → "20"，".5" 这类要补上前导零
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-"):
        text = "0"
    if text.startswith("."):
        text = "0" + text
    if text.startswith("-."):
        text = "-0" + text[1:]

    return text
