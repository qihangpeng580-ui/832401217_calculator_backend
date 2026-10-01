"""测试：SQLite 存储层。

运行（在项目根目录下）：
    py -3.12 -m unittest tests.test_store -v

每条测试都在**临时目录**里建一个新的数据库文件，互不影响，
也不会污染 data/ 下的正式数据。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.model.sqlite_store import SqliteStore


class StoreTestCase(unittest.TestCase):
    """基类：为每条测试准备一个独立的临时数据库。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.store = SqliteStore(self.db_path)
        self.store.init_schema()

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestSchema(StoreTestCase):
    """建表。"""

    def test_init_is_idempotent(self) -> None:
        """重复建表不能报错（服务重启时会再调一次）。"""
        self.store.init_schema()
        self.store.init_schema()
        self.assertEqual(self.store.count(), 0)

    def test_db_file_created(self) -> None:
        self.assertTrue(self.db_path.exists())

    def test_creates_parent_directory(self) -> None:
        """目录不存在时应该自动创建，而不是报错。"""
        nested = Path(self._tmp.name) / "a" / "b" / "c.db"
        store = SqliteStore(nested)
        store.init_schema()
        self.assertTrue(nested.exists())


class TestInsert(StoreTestCase):
    """插入记录。"""

    def test_insert_returns_full_record(self) -> None:
        record = self.store.insert("12+8", "20")
        self.assertEqual(record["expression"], "12+8")
        self.assertEqual(record["result"], "20")
        self.assertGreater(record["id"], 0)
        self.assertIn("createdAt", record)

    def test_id_increases(self) -> None:
        first = self.store.insert("1+1", "2")
        second = self.store.insert("2+2", "4")
        self.assertGreater(second["id"], first["id"])

    def test_count_after_inserts(self) -> None:
        self.store.insert("1+1", "2")
        self.store.insert("2+2", "4")
        self.assertEqual(self.store.count(), 2)

    def test_unicode_supported(self) -> None:
        """表达式里出现中文或特殊字符也要能存能取（防御性）。"""
        record = self.store.insert("1+1", "2")
        fetched = self.store.get(record["id"])
        assert fetched is not None
        self.assertEqual(fetched["expression"], "1+1")

    def test_negative_result_stored_as_text(self) -> None:
        record = self.store.insert("3-10", "-7")
        fetched = self.store.get(record["id"])
        assert fetched is not None
        self.assertEqual(fetched["result"], "-7")

    def test_decimal_result_keeps_precision(self) -> None:
        """★ 结果存 TEXT 而不是 REAL 的意义。

        如果存成浮点，0.3 可能在读回来时变成 0.29999999999999998。
        """
        record = self.store.insert("0.1+0.2", "0.3")
        fetched = self.store.get(record["id"])
        assert fetched is not None
        self.assertEqual(fetched["result"], "0.3")


class TestList(StoreTestCase):
    """查询列表。"""

    def test_empty_list(self) -> None:
        self.assertEqual(self.store.list_recent(), [])

    def test_newest_first(self) -> None:
        """最新的必须排在最前面 —— 前端打开就看最近的记录。"""
        self.store.insert("1+1", "2")
        self.store.insert("2+2", "4")
        self.store.insert("3+3", "6")
        expressions = [r["expression"] for r in self.store.list_recent()]
        self.assertEqual(expressions, ["3+3", "2+2", "1+1"])

    def test_limit(self) -> None:
        for i in range(10):
            self.store.insert(f"{i}+0", str(i))
        self.assertEqual(len(self.store.list_recent(limit=3)), 3)

    def test_limit_returns_newest(self) -> None:
        for i in range(10):
            self.store.insert(f"{i}+0", str(i))
        result = self.store.list_recent(limit=2)
        self.assertEqual([r["expression"] for r in result], ["9+0", "8+0"])

    def test_keyword_search(self) -> None:
        self.store.insert("12+8", "20")
        self.store.insert("5*5", "25")
        found = self.store.list_recent(keyword="12")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["expression"], "12+8")

    def test_keyword_search_operator(self) -> None:
        self.store.insert("12+8", "20")
        self.store.insert("5*5", "25")
        found = self.store.list_recent(keyword="*")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["expression"], "5*5")

    def test_keyword_no_match(self) -> None:
        self.store.insert("12+8", "20")
        self.assertEqual(self.store.list_recent(keyword="999"), [])

    def test_count_with_keyword(self) -> None:
        self.store.insert("12+8", "20")
        self.store.insert("5*5", "25")
        self.assertEqual(self.store.count(keyword="+"), 1)
        self.assertEqual(self.store.count(), 2)


class TestGet(StoreTestCase):
    """按 id 取单条。"""

    def test_get_exists(self) -> None:
        record = self.store.insert("12+8", "20")
        fetched = self.store.get(record["id"])
        assert fetched is not None
        self.assertEqual(fetched["expression"], "12+8")

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.store.get(99999))


class TestDelete(StoreTestCase):
    """★ 删除指定记录 —— 作业评分表里单独占 10 分。"""

    def test_delete_existing(self) -> None:
        record = self.store.insert("12+8", "20")
        self.assertTrue(self.store.delete(record["id"]))
        self.assertIsNone(self.store.get(record["id"]))
        self.assertEqual(self.store.count(), 0)

    def test_delete_missing_returns_false(self) -> None:
        """删一个不存在的 id 要返回 False，让上层回 404 而不是 204。"""
        self.assertFalse(self.store.delete(99999))

    def test_delete_only_target(self) -> None:
        """★ 只删指定的那一条，别的不受影响。"""
        first = self.store.insert("1+1", "2")
        second = self.store.insert("2+2", "4")
        third = self.store.insert("3+3", "6")

        self.store.delete(second["id"])

        remaining = [r["id"] for r in self.store.list_recent()]
        self.assertIn(first["id"], remaining)
        self.assertIn(third["id"], remaining)
        self.assertNotIn(second["id"], remaining)

    def test_delete_twice(self) -> None:
        record = self.store.insert("1+1", "2")
        self.assertTrue(self.store.delete(record["id"]))
        self.assertFalse(self.store.delete(record["id"]))


class TestDeleteAll(StoreTestCase):
    """清空全部（扩展功能）。"""

    def test_delete_all_returns_count(self) -> None:
        for i in range(5):
            self.store.insert(f"{i}+0", str(i))
        self.assertEqual(self.store.delete_all(), 5)
        self.assertEqual(self.store.count(), 0)

    def test_delete_all_on_empty(self) -> None:
        self.assertEqual(self.store.delete_all(), 0)


class TestStats(StoreTestCase):
    """统计（扩展功能）。"""

    def test_stats_empty(self) -> None:
        stats = self.store.stats()
        self.assertEqual(stats["total"], 0)

    def test_stats_counts_operators(self) -> None:
        self.store.insert("1+1", "2")
        self.store.insert("2+2", "4")
        self.store.insert("3*3", "9")
        stats = self.store.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["byOperator"]["加"], 2)
        self.assertEqual(stats["byOperator"]["乘"], 1)
        self.assertEqual(stats["byOperator"]["减"], 0)


if __name__ == "__main__":
    unittest.main()
