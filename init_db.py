"""单独建数据库脚本 —— 不启动服务，只准备数据库文件。

用途：
    · 部署前先建好库，避免第一次请求时才建（虽然那样也能工作）
    · 检查数据库的当前状态（有多少条记录）
    · 清空所有历史（带确认提示）

用法：
    py -3.12 init_db.py                   建库/查看状态
    py -3.12 init_db.py --clear            建库并清空所有历史
    py -3.12 init_db.py --db other.db      指定另一个文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model.sqlite_store import SqliteStore  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "calculator.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="init_db.py",
        description="初始化计算器后端的 SQLite 数据库",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"数据库文件路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--clear", action="store_true", help="清空所有历史记录")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    store = SqliteStore(db_path)

    existed = db_path.exists()
    store.init_schema()
    print(f"数据库：{db_path}")
    print(f"状态：{'已存在，表结构已确认' if existed else '已新建'}")

    if args.clear:
        deleted = store.delete_all()
        print(f"已清空 {deleted} 条历史记录")

    total = store.count()
    print(f"当前历史记录数：{total}")

    if total:
        print("\n最近 5 条：")
        for record in store.list_recent(limit=5):
            print(f"  [{record['id']}] {record['expression']} = {record['result']}   ({record['createdAt']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
