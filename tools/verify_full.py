"""临时验证脚本：临时填上 parser 的两个 TODO，跑完整黑盒验收，然后还原。

用途：确认**整条链路**（HTTP → service → 解析 → 求值 → SQLite）都正确，
      这样把 TODO 骨架交出去时，可以确定"填完就一定全绿"。

运行：py -3.12 tools/verify_full.py

注意：无论成功失败，脚本最后都会把 parser.py 还原成 TODO 骨架。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARSER = PROJECT_ROOT / "src" / "calculator" / "parser.py"

EXPRESSION_IMPL = '''    def _parse_expression(self) -> Node:
        """解析"加减"这一层。"""
        node = self._parse_term()
        while (op := self._match_operator("+", "-")) is not None:
            right = self._parse_term()
            node = BinaryOp(op, node, right)
        return node
'''

TERM_IMPL = '''    def _parse_term(self) -> Node:
        """解析"乘除"这一层。"""
        node = self._parse_factor()
        while (op := self._match_operator("*", "/")) is not None:
            right = self._parse_factor()
            node = BinaryOp(op, node, right)
        return node
'''


def run(cmd: list[str]) -> tuple[int, str]:
    """跑一条命令，返回 (退出码, 输出尾部)。"""
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output


def main() -> int:
    original = PARSER.read_text(encoding="utf-8")

    patched = re.sub(
        r'    def _parse_expression\(self\) -> Node:.*?(?=\n    def _parse_term)',
        EXPRESSION_IMPL.rstrip() + "\n",
        original,
        flags=re.DOTALL,
    )
    patched = re.sub(
        r'    def _parse_term\(self\) -> Node:.*?(?=\n    def _parse_factor)',
        TERM_IMPL.rstrip() + "\n",
        patched,
        flags=re.DOTALL,
    )

    if patched == original:
        print("替换失败：parser.py 里没找到 TODO 函数")
        return 2

    try:
        PARSER.write_text(patched, encoding="utf-8")

        print("=" * 62)
        print("临时填上解析器，验证整条链路（跑完会自动还原）")
        print("=" * 62)

        for label, cmd in [
            ("tokenizer 测试", [sys.executable, "-m", "unittest", "tests.test_tokenizer"]),
            ("parser 测试", [sys.executable, "-m", "unittest", "tests.test_parser"]),
            ("calculator 测试", [sys.executable, "-m", "unittest", "tests.test_calculator"]),
            ("store 测试", [sys.executable, "-m", "unittest", "tests.test_store"]),
            ("黑盒验收（真实 HTTP）", [sys.executable, "tools/blackbox.py"]),
        ]:
            code, output = run(cmd)
            tail = [l for l in output.strip().splitlines() if l.strip()][-3:]
            status = "通过" if code == 0 else "失败"
            print(f"\n[{status}] {label}")
            for line in tail:
                print("    " + line)
            if code != 0 and label != "黑盒验收（真实 HTTP）":
                # 单元测试失败要看到细节
                print("    （输出尾部）")
                for line in output.strip().splitlines()[-15:]:
                    print("      " + line)

        return 0
    finally:
        PARSER.write_text(original, encoding="utf-8")
        print("\n已把 parser.py 还原为 TODO 骨架")


if __name__ == "__main__":
    raise SystemExit(main())
