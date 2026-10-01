"""临时验证脚本：把 parser 的两个 TODO 实现一遍，跑通测试后立即撤回。

用途：确认骨架本身正确（语法规则、工具方法、错误处理都对），
      这样把骨架交给别人填时，测试失败一定是"还没填"，而不是"骨架有问题"。

运行：py -3.12 tools/verify_skeleton.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSER = ROOT / "src" / "calculator" / "parser.py"

# 两个函数的正确实现（临时插入用）
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


def main() -> int:
    original = PARSER.read_text(encoding="utf-8")

    # 用实现替换掉两个 raise NotImplementedError 的函数体
    patched = original

    # 替换 _parse_expression 的整个函数体（从 def 到下一个 def 之前）
    patched = re.sub(
        r'    def _parse_expression\(self\) -> Node:.*?(?=\n    def _parse_term)',
        EXPRESSION_IMPL.rstrip() + "\n",
        patched,
        flags=re.DOTALL,
    )
    patched = re.sub(
        r'    def _parse_term\(self\) -> Node:.*?(?=\n    def _parse_factor)',
        TERM_IMPL.rstrip() + "\n",
        patched,
        flags=re.DOTALL,
    )

    if patched == original:
        print("替换失败：没有匹配到 TODO 函数，请检查 parser.py 是否被改动过")
        return 2

    try:
        PARSER.write_text(patched, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "tests.test_parser"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        tail = (result.stderr or "").strip().splitlines()[-6:]
        print("骨架验证结果：")
        for line in tail:
            print("  " + line)
        return 0 if result.returncode == 0 else 1
    finally:
        # ★ 无论成功失败，一定要把 TODO 骨架还原回去
        PARSER.write_text(original, encoding="utf-8")
        print("已还原为 TODO 骨架")


if __name__ == "__main__":
    raise SystemExit(main())
