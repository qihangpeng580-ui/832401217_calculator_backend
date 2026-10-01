"""语法分析器（parser）—— 把记号序列变成语法树（AST）。

★ 这个文件里有两个函数留给你实现（标了 TODO），其余部分我写好了。
   要填的是 ``_parse_expression`` 和 ``_parse_term``，共约 20 行。
   把 tests/test_parser.py 跑通就算完成。

------------------------------------------------------------------
它在计算链路里的位置
------------------------------------------------------------------

    tokenizer.py  →  [NUMBER(1), OP(+), NUMBER(2), OP(*), NUMBER(3)]
        ↓  本模块
    语法树        BinaryOp(+, 1, BinaryOp(*, 2, 3))
        ↓  evaluator.py
    结果          7           ← 注意是 7 不是 9：先算乘法

------------------------------------------------------------------
为什么要有"语法树"这一层
------------------------------------------------------------------

直接把记号算完不行吗？行，但那样"谁先算"这件事就糊在代码里了。
语法树把**优先级**这件事**画出来**：

        +                ← 最上面的是最后算的
       / \\
      1   *             ← 乘法在下面，所以先算
         / \\
        2   3

树的结构本身就表达了"先算 2*3，再加 1"。这样求值那一步变得非常简单：
**后序遍历**（先算子节点，再算自己）。

------------------------------------------------------------------
文法（递归下降）
------------------------------------------------------------------

递归下降的写法是"一个优先级一层函数"，从**最低优先级**开始往上写：

    expression := term (("+" | "-") term)*      ← 加减（优先级最低）
    term       := factor (("*" | "/") factor)*  ← 乘除（优先级高一层）
    factor     := ("+" | "-") factor            ← 一元正负号，如 -5、3*-2
                | "(" expression ")"
                | NUMBER

读法：一个表达式由"若干项用加减连起来"构成；
      一个项由"若干因子用乘除连起来"构成；
      一个因子可以是"带正负号的因子"、"括号包起来的表达式"、或"一个数字"。

为什么"一个优先级一层函数"就能实现优先级：
    因为 expression 里要调 term，而 term 里要调 factor。
    于是解析 "1+2*3" 时，走到 "+" 右边会去调 term，
    而 term 会把 "2*3" 整个吃下去当作一个整体，而不是只取 "2"。
    **"谁被谁包含"就决定了"谁先算"。**

关于一元负号：它在 factor 这一层处理，所以不写"强制优先级"也能正确工作：
    "3*-2"  →  term 里遇到 "*"，右边去调 factor，factor 看到 "-"，
               于是返回 UnaryOp(-, 2)，整个 term 得到 BinaryOp(*, 3, -2)。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Union

from src.calculator.tokenizer import Token, TokenType, tokenize
from src.common.errors import InvalidExpressionError


# ==================================================================
# 语法树的节点定义
# ==================================================================


@dataclass(frozen=True)
class Number:
    """一个数字节点。"""

    value: Decimal


@dataclass(frozen=True)
class UnaryOp:
    """一元运算节点，目前只有取负和取正。

    op    "+" 或 "-"
    operand  被作用的那个子节点
    """

    op: str
    operand: "Node"


@dataclass(frozen=True)
class BinaryOp:
    """二元运算节点。

    op    "+"、"-"、"*"、"/"
    left  左操作数
    right 右操作数
    """

    op: str
    left: "Node"
    right: "Node"


# 语法树节点的联合类型，只是写注释用的
Node = Union[Number, UnaryOp, BinaryOp]


# ==================================================================
# 解析器
# ==================================================================


class Parser:
    """把记号序列解析成语法树。

    用"游标 + 查看下一个记号"的方式推进：
        self._pos     当前看到第几个记号
        _peek()       看看当前记号是什么（不前进）
        _advance()    取走当前记号并前进一格
    """

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # --------------------------------------------------------------
    # 工具方法（已写好，直接用）
    # --------------------------------------------------------------

    def _peek(self) -> Token | None:
        """看看当前记号，不前进。到头了返回 None。"""
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        """取走当前记号并前进一格。"""
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _is_operator(self, *chars: str) -> bool:
        """当前记号是不是指定的这些运算符之一。

        例：self._is_operator("+", "-")
        """
        token = self._peek()
        return (
            token is not None
            and token.kind is TokenType.OPERATOR
            and token.value in chars
        )

    def _match_operator(self, *chars: str) -> str | None:
        """如果当前是这些运算符之一，就取走并返回它；否则返回 None。"""
        if self._is_operator(*chars):
            return self._advance().value  # type: ignore[return-value]
        return None

    # --------------------------------------------------------------
    # 对外入口（已写好）
    # --------------------------------------------------------------

    def parse(self) -> Node:
        """解析整个表达式。

        除了表达式本身，**不能有别的记号剩下** ——
        比如 "1+2)" 这种多出一个右括号的，要在解析完整表达式之后被发现。
        """
        node = self._parse_expression()

        leftover = self._peek()
        if leftover is not None:
            raise InvalidExpressionError(
                f"表达式有多余的内容：{leftover.value!r}（第 {leftover.pos + 1} 个字符）"
            )

        return node

    # --------------------------------------------------------------
    # ★ 下面三个是本文件的核心，前两个留给你实现
    # --------------------------------------------------------------

    def _parse_expression(self) -> Node:
        """解析"加减"这一层。对应文法：expression := term (("+" | "-") term)*

        ============ TODO：你来写（约 10 行） ============

        思路（左边先算，所以叫"左结合"）：
            1. 先解析出左边的一个 term：  node = self._parse_term()
            2. 循环：只要当前记号是 "+" 或 "-"：
                 a. 用 self._match_operator("+", "-") 取走它，拿到 op
                 b. 再解析出右边的一个 term：  right = self._parse_term()
                 c. 把两者组成新节点：node = BinaryOp(op, node, right)
                    ★ 注意是用**原来的 node 当左子树**，
                      这样 "1+2+3" 会自然变成 ((1+2)+3)，也就是从左往右算。
            3. 返回 node

        为什么用"循环 + 每轮把 node 当左子树"就能实现左结合：
            "1-2-3" 应该等于 (1-2)-3 = -4，而不是 1-(2-3) = 2。
            因为每转一圈都把"到目前为止的结果"放在左边，所以天然是从左往右。

        提示：_match_operator 会在不匹配时返回 None，所以可以直接写
              while (op := self._match_operator("+", "-")) is not None:
        =================================================
        """
        raise NotImplementedError("TODO: 实现 _parse_expression —— 见上面的注释")

    def _parse_term(self) -> Node:
        """解析"乘除"这一层。对应文法：term := factor (("*" | "/") factor)*

        ============ TODO：你来写（约 8 行） ============

        和 _parse_expression 几乎一模一样，只有两点不同：
            1. 调的是 self._parse_factor()（而不是 _parse_term）
            2. 匹配的运算符是 "*" 和 "/"

        为什么它比 _parse_expression"优先级高"：
            因为 _parse_expression 调用了 _parse_term，所以乘除会先被组合成子树。
            这个文件开头的文法说明里有图示。
        =================================================
        """
        raise NotImplementedError("TODO: 实现 _parse_term —— 见上面的注释")

    def _parse_factor(self) -> Node:
        """解析"因子"这一层。对应文法：

            factor := ("+" | "-") factor     ← 一元正负号
                    | "(" expression ")"     ← 括号
                    | NUMBER                 ← 数字

        这一层**我已经写好了**，你可以对照理解上面两个该怎么写。
        """
        token = self._peek()
        if token is None:
            raise InvalidExpressionError("表达式不完整：结尾缺少数字或括号")

        # ---- 情况一：一元正负号 ----
        # 注意这里用的是**递归**："-" 后面还可以再来一个 "-"，即 "--5" 也合法。
        if self._is_operator("+", "-"):
            op = self._advance().value
            operand = self._parse_factor()  # 递归解析被作用的因子
            return UnaryOp(str(op), operand)

        # ---- 情况二：括号 ----
        if token.kind is TokenType.LPAREN:
            self._advance()  # 吃掉 "("
            inner = self._parse_expression()  # 括号里又是一个完整表达式
            closing = self._peek()
            if closing is None or closing.kind is not TokenType.RPAREN:
                raise InvalidExpressionError(
                    f"括号不匹配：第 {token.pos + 1} 个字符的左括号没有对应的右括号"
                )
            self._advance()  # 吃掉 ")"
            return inner

        # ---- 情况三：数字 ----
        if token.kind is TokenType.NUMBER:
            self._advance()
            return Number(token.value)  # type: ignore[arg-type]

        # ---- 其余情况：语法错误 ----
        # 例如 "(1+)" 这种：括号里解析完 1+ 之后，期待一个因子却遇到了 ")"
        if token.kind is TokenType.RPAREN:
            raise InvalidExpressionError(
                f"右括号前缺少数字或表达式（第 {token.pos + 1} 个字符）"
            )
        raise InvalidExpressionError(
            f"表达式不完整：{token.value!r} 的位置不对（第 {token.pos + 1} 个字符）"
        )


def parse(expression: str) -> Node:
    """对外接口：字符串 → 语法树。

    这是其他模块唯一需要调用的函数（tokenize 和 Parser 都是内部细节）。

    Args:
        expression: 用户输入的表达式

    Returns:
        语法树的根节点

    Raises:
        InvalidExpressionError: 表达式不合法
    """
    tokens = tokenize(expression)
    return Parser(tokens).parse()
