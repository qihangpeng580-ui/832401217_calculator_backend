"""历史记录服务 —— 计算与持久化的编排。

分工：
    CalculatorService   只管算（无状态，不碰数据库）
    SqliteStore         只管存（不关心结果是怎么来的）
    HistoryService      把两者串起来：算完顺手存一条，并提供历史的查/删接口

为什么要把"算"和"存"分开：
    1. 算的部分可以脱离数据库测试（tests/test_calculator.py 就不需要建库）；
    2. 存的部分可以脱离计算测试（tests/test_store.py 直接塞假数据）；
    3. 如果哪天不想自动保存历史，只需要改这一层，两个底层模块都不用动。

一个设计选择：**计算失败时不写历史**。
    只有成功算出结果才入库。理由：历史记录是"算过的式子"，
    一个非法表达式不构成一次有效的计算，记进去反而会让用户困惑。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.common.errors import RecordNotFoundError
from src.model.sqlite_store import SqliteStore
from src.service.calculator_service import CalculationOutcome, CalculatorService


class HistoryService:
    """计算 + 历史持久化。"""

    def __init__(self, db_path: str | Path, calculator: CalculatorService | None = None) -> None:
        self._store = SqliteStore(db_path)
        self._calculator = calculator or CalculatorService()

    def init(self) -> None:
        """启动时调用一次：建表。"""
        self._store.init_schema()

    # ---------------------------------------------------------------- 算 + 存

    def calculate_and_save(self, expression: str) -> CalculationOutcome:
        """计算一个表达式，并把结果存进数据库。

        Args:
            expression: 用户输入的表达式

        Returns:
            计算结果

        Raises:
            InvalidExpressionError / DivisionByZeroError: 表达式不合法（此时**不写库**）
        """
        outcome = self._calculator.calculate(expression)

        # 只有成功算出结果才写历史。
        # 放在 calculate 之后，意味着抛异常时这一行根本不会被执行 ——
        # 这就是"失败不写库"的实现方式，不需要额外判断。
        self._store.insert(outcome.expression, outcome.result)

        return outcome

    # ---------------------------------------------------------------- 查

    def list_history(self, limit: int = 50, keyword: str | None = None) -> dict:
        """取历史列表（含总数，便于前端分页）。"""
        records = self._store.list_recent(limit=limit, keyword=keyword)
        return {
            "items": records,
            "total": self._store.count(),
            "limit": limit,
            "keyword": keyword or "",
        }

    def stats(self) -> dict:
        """统计信息（扩展功能）。"""
        return self._store.stats()

    # ---------------------------------------------------------------- 删

    def delete_history(self, record_id: int) -> None:
        """删除一条历史记录。

        Raises:
            RecordNotFoundError: 该 id 不存在
                —— 用异常而不是返回 False，是为了让 HTTP 层统一按错误码回 404，
                   不用在每处判断返回值。
        """
        if not self._store.delete(record_id):
            raise RecordNotFoundError(f"历史记录 {record_id} 不存在或已被删除")

    def delete_all_history(self) -> int:
        """清空全部历史，返回删掉的条数（扩展功能）。"""
        return self._store.delete_all()
