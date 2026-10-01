"""SQLite 存储层 —— 计算历史的持久化。

作业要求「Persist calculation history in the back-end database」，
所以历史**必须落在后端数据库里**，不能存在前端的 localStorage，
也不能只放在内存里（进程一重启就没了）。

为什么选 SQLite：
    1. Python 标准库自带（``import sqlite3``），不需要装任何数据库服务；
    2. 数据存成一个文件，拷走这个文件就完成了备份；
    3. 助教拿到代码后，不需要配 MySQL 就能跑起来。

本模块只负责"怎么存"，不负责"什么算合法"——那是 service 层的事。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

# 建表语句。
#
# result 为什么存 TEXT 而不是 REAL：
#   计算结果是 Decimal，用 REAL 存会变成二进制浮点，
#   0.1+0.2 存进去再读出来可能就不是 0.3 了。
#   存成 TEXT 可以保持十进制精确，读取时再转回 Decimal。
#
# created_at 存 ISO-8601 文本，便于排序和直接显示。
SCHEMA = """
CREATE TABLE IF NOT EXISTS calculation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expression  TEXT    NOT NULL,
    result      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

-- 按时间倒序查列表是最高频的操作（前端打开就要拉最近若干条），
-- 所以给 created_at 建索引。
CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON calculation_history (created_at DESC);
"""


class SqliteStore:
    """计算历史的 SQLite 存储。

    用法：
        store = SqliteStore("data/calculator.db")
        store.init_schema()
        record = store.insert("12+8", "20")

    关于连接：
        每次操作开一个新连接再关掉。SQLite 打开本地文件的成本极低，
        这样做的好处是**不需要在 HTTP 多线程环境里共享连接**
        （sqlite3 的连接对象默认不能跨线程使用），少一类并发问题。
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    # ---------------------------------------------------------------- 基础设施

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开连接，用完自动提交并关闭。

        用 contextmanager 是为了保证异常时也能正确关闭，
        调用方只需要写 with self._connect() as conn: ...
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        # row_factory 让查询结果可以按列名取值：row["expression"]
        # 不加这一行只能按下标取：row[1]，可读性差很多。
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """建表（幂等：表已存在时什么也不做）。

        服务启动时调用一次。用 IF NOT EXISTS 保证重复调用安全。
        """
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- 增

    def insert(self, expression: str, result: str) -> dict:
        """插入一条计算记录。

        Args:
            expression: 用户输入的表达式（原样保存）
            result: 规范化后的结果字符串

        Returns:
            新插入的整条记录（含自增 id 与创建时间）
        """
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO calculation_history (expression, result, created_at) "
                "VALUES (?, ?, ?)",
                (expression, result, created_at),
            )
            new_id = int(cursor.lastrowid or 0)

        return {
            "id": new_id,
            "expression": expression,
            "result": result,
            "createdAt": created_at,
        }

    # ---------------------------------------------------------------- 查

    def list_recent(self, limit: int = 50, keyword: str | None = None) -> list[dict]:
        """按时间倒序取历史记录。

        Args:
            limit: 最多取多少条
            keyword: 可选。按表达式做模糊匹配（对应扩展功能"历史搜索"）

        Returns:
            记录列表，最新的在最前面
        """
        sql = "SELECT id, expression, result, created_at FROM calculation_history"
        params: list[object] = []

        if keyword:
            sql += " WHERE expression LIKE ?"
            params.append(f"%{keyword}%")

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._to_dict(row) for row in rows]

    def count(self, keyword: str | None = None) -> int:
        """统计记录条数（分页与统计面板要用）。"""
        sql = "SELECT COUNT(*) AS n FROM calculation_history"
        params: list[object] = []
        if keyword:
            sql += " WHERE expression LIKE ?"
            params.append(f"%{keyword}%")

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()

        return int(row["n"]) if row else 0

    def get(self, record_id: int) -> dict | None:
        """按 id 取一条记录，不存在返回 None。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, expression, result, created_at FROM calculation_history WHERE id = ?",
                (record_id,),
            ).fetchone()

        return self._to_dict(row) if row else None

    # ---------------------------------------------------------------- 删

    def delete(self, record_id: int) -> bool:
        """删除一条记录。

        Returns:
            True 表示确实删掉了一条；False 表示这个 id 本来就不存在。
            返回布尔的用途：service 层据此决定"返回 404 还是 204"。
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM calculation_history WHERE id = ?", (record_id,)
            )
            deleted = cursor.rowcount

        return deleted > 0

    def delete_all(self) -> int:
        """清空全部历史（扩展功能）。返回删掉的条数。

        实现说明：必须在**删除之前**统计条数。
        一开始写成"删除后读 cursor.rowcount"，但 SQLite 在全表 DELETE 时
        rowcount 可能返回 -1，而且删除后就再也查不到原来的条数了。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM calculation_history"
            ).fetchone()
            before = int(row["n"]) if row else 0
            conn.execute("DELETE FROM calculation_history")

        return before

    # ---------------------------------------------------------------- 统计

    def stats(self) -> dict:
        """统计信息（扩展功能"统计面板"用）。"""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM calculation_history"
            ).fetchone()["n"]

            # 按表达式里出现的运算符统计次数。
            # 用 SQL 的 LIKE 累加，避免把所有记录拉到 Python 里再遍历。
            operator_counts = {}
            for op, label in (("+", "加"), ("-", "减"), ("*", "乘"), ("/", "除")):
                n = conn.execute(
                    "SELECT COUNT(*) AS n FROM calculation_history WHERE expression LIKE ?",
                    (f"%{op}%",),
                ).fetchone()["n"]
                operator_counts[label] = int(n)

        return {"total": int(total), "byOperator": operator_counts}

    # ---------------------------------------------------------------- 内部工具

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        """把数据库行转成给前端用的字典。

        字段名用 camelCase（createdAt），与前端约定一致；
        数据库列名保持 snake_case（created_at），符合 SQL 习惯。
        """
        return {
            "id": int(row["id"]),
            "expression": row["expression"],
            "result": row["result"],
            "createdAt": row["created_at"],
        }
