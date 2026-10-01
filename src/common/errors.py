"""统一错误定义 —— 全后端只有这一处决定"什么错配什么 HTTP 状态码"。

为什么要把错误集中定义：
    1. 前端拿到的错误码只有一个来源，不会出现同一个意思两个码。
    2. 新增一种错误时，只需要在这里加一个类，HTTP 状态码自然就定好了，
       不用在业务代码里到处写 "return 400"。
    3. 前端 ui.js 里有一张"错误码 → 中文提示"的翻译表，
       这里的 ERROR_CODE 必须和那张表的键**保持一致**。

错误码一览（与前端 SERVER_ERROR_TEXT 对应）：

    INVALID_EXPRESSION    表达式不合法（语法错、非法字符、括号不匹配）  → 400
    DIVISION_BY_ZERO      除数为零                                   → 422
    EXPRESSION_TOO_LONG   表达式过长                                 → 413
    RECORD_NOT_FOUND      历史记录不存在                             → 404
    BAD_REQUEST           请求格式不对（不是合法 JSON、缺字段）        → 400
    INTERNAL_ERROR        服务器内部错误                             → 500
"""

from __future__ import annotations


class CalcError(Exception):
    """所有业务错误的基类。

    属性：
        error_code   给前端看的机器可读错误码（前端用它查中文提示）
        message      给用户看的中文说明
        http_status  这个错误应该回什么 HTTP 状态码

    为什么状态码要挂在异常上，而不是在捕获处判断类型：
        判断类型会写成 if isinstance(exc, DivisionByZero) ... 这种链，
        每加一种错误就要改一次；挂在异常上则天然一一对应。
    """

    error_code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "") -> None:
        self.message = message or self.__class__.__doc__ or "服务器内部错误"
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转成响应体里 errors 部分的形状（供 controller 使用）。"""
        return {"errorCode": self.error_code, "message": self.message}


class InvalidExpressionError(CalcError):
    """表达式不合法。"""

    error_code = "INVALID_EXPRESSION"
    http_status = 400


class DivisionByZeroError(CalcError):
    """除数为零。"""

    error_code = "DIVISION_BY_ZERO"
    http_status = 422


class ExpressionTooLongError(CalcError):
    """表达式过长。"""

    error_code = "EXPRESSION_TOO_LONG"
    http_status = 413


class RecordNotFoundError(CalcError):
    """历史记录不存在。"""

    error_code = "RECORD_NOT_FOUND"
    http_status = 404


class BadRequestError(CalcError):
    """请求格式不对。"""

    error_code = "BAD_REQUEST"
    http_status = 400
