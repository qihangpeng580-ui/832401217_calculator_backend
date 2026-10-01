"""黑盒验收脚本 —— 用真实 HTTP 请求走一遍完整流程。

运行（在项目根目录下）：
    py -3.12 tools/blackbox.py

它会：
    1. 在临时目录建一个空数据库，起一个真实的后端服务（随机端口）；
    2. 用 urllib 发**真实 HTTP 请求**，把作业要求的四件事都验一遍：
         ① 基本运算（12+8 = 20）
         ② 复合表达式（优先级、括号、一元正负号、小数、非法表达式、除零）
         ③ 历史持久化（算完能查到；重启服务后**依然在**）
         ④ 删除指定记录（删掉后真的没了，其余不受影响）
    3. 关掉服务，删除临时文件。

为什么要有这个脚本（而不是只有单元测试）：
    单元测试是"直接调函数"，绕过了 HTTP 这一层。
    而作业要求的交付物是一个**能被网络访问的服务** ——
    所以必须有一条测试是"真的通过网络调它"，否则会出现
    "函数都对、服务却跑不起来"的情况（前端那次 file:// 的坑就是这么来的）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

passed = 0
failures: list[str] = []


def _drain(proc: subprocess.Popen, sink: list[str]) -> None:
    """把子进程的输出持续读走，避免管道缓冲区写满导致子进程卡死。

    读到的内容存进 sink，只在需要排查时才打印。
    """
    if proc.stdout is None:
        return
    for line in proc.stdout:
        sink.append(line)


def check(name: str, actual: object, expected: object) -> None:
    """断言并记录。不抛异常，跑完所有用例后统一报告。"""
    global passed
    if actual == expected:
        passed += 1
        print(f"  OK   {name}")
    else:
        failures.append(f"{name}\n         期望：{expected!r}\n         实际：{actual!r}")
        print(f"  FAIL {name}")


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    """发一个 HTTP 请求，返回 (状态码, 响应体)。

    204 没有响应体，返回空字符串。
    """
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None

    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else "")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # noqa: BLE001
        # 连接被服务端切断时会走到这里。把真实异常抛出去，
        # 否则只会看到一句 "Remote end closed connection" 而不知道该看哪里。
        raise RuntimeError(
            f"请求 {method} {path} 时连接失败：{type(exc).__name__}: {exc}"
        ) from exc


def wait_for_server(timeout: float = 15.0) -> bool:
    """等服务的健康检查能通。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = request("GET", "/api/health")
            if status == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "blackbox.db"

        print("=" * 62)
        print("黑盒验收：用真实 HTTP 请求验证前后端分离计算器的后端")
        print("=" * 62)

        # ---------------------------------------------------------- 启动服务
        print("\n[0] 启动服务")
        proc = subprocess.Popen(
            [sys.executable, "run.py", "--port", str(PORT), "--db", str(db_path)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # 后台读走子进程的输出。
        # ★ 必须读！如果只用 PIPE 不读，管道缓冲区写满后子进程会阻塞 —— 表现是
        #   "服务莫名其妙卡住"。这里用一个线程持续读，把内容留在内存里，
        #   只有启动失败时才打印出来。
        captured: list[str] = []
        reader = threading.Thread(target=_drain, args=(proc, captured), daemon=True)
        reader.start()

        try:
            if not wait_for_server():
                print("  服务没能启动，输出如下：")
                if proc.stdout:
                    print(proc.stdout.read())
                return 2
            print(f"  OK   服务已启动：{BASE}")

            # ------------------------------------------------------ 健康检查
            status, body = request("GET", "/api/health")
            check("GET /api/health 返回 200", status, 200)

            # ------------------------------------------------------ ① 基本运算
            print("\n[1] 基本运算（作业评分项 15 分）")
            for expression, expected in [
                ("12+8", "20"),
                ("9-4", "5"),
                ("5*8", "40"),
                ("10/2", "5"),
            ]:
                status, body = request("POST", "/api/calculate", {"expression": expression})
                check(f"{expression} = {expected}", body.get("data", {}).get("result") if isinstance(body, dict) and body.get("success") else f"HTTP {status}", expected)

            # ------------------------------------------------------ ② 复合表达式
            print("\n[2] 复合表达式（作业评分项 15 分）")
            cases = [
                ("1+2*3", "7", "运算优先级"),
                ("(1+2)*3", "9", "括号"),
                ("10/2+7", "12", "优先级 + 除法"),
                ("8-3*2", "2", "优先级 + 减法"),
                ("-5+8", "3", "一元负号在开头"),
                ("3*-2", "-6", "一元负号在运算符后"),
                ("0.1+0.2", "0.3", "小数精度（不能用浮点）"),
                ("100/5/2", "10", "左结合"),
                ("2*(3+(4-1))", "12", "嵌套括号"),
            ]
            for expression, expected, note in cases:
                status, body = request("POST", "/api/calculate", {"expression": expression})
                got = body.get("data", {}).get("result") if isinstance(body, dict) and body.get("success") else f"HTTP {status}"
                check(f"{expression} = {expected}（{note}）", got, expected)

            print("\n[3] 非法表达式与除零（作业要求）")
            status, body = request("POST", "/api/calculate", {"expression": "1+2*"})
            check("非法表达式返回 400", status, 400)
            check("非法表达式错误码", body.get("errorCode") if isinstance(body, dict) else None, "INVALID_EXPRESSION")

            status, body = request("POST", "/api/calculate", {"expression": "(1+2"})
            check("括号不匹配返回 400", status, 400)

            status, body = request("POST", "/api/calculate", {"expression": "1+a"})
            check("非法字符返回 400", status, 400)

            status, body = request("POST", "/api/calculate", {"expression": "10/0"})
            check("除零返回 422", status, 422)
            check("除零错误码", body.get("errorCode") if isinstance(body, dict) else None, "DIVISION_BY_ZERO")

            status, body = request("POST", "/api/calculate", {"expression": "__import__('os')"})
            check("代码注入被拒绝", status, 400)

            status, body = request("POST", "/api/calculate", {})
            check("缺少 expression 字段返回 400", status, 400)

            # ------------------------------------------------------ ③ 历史持久化
            print("\n[4] 历史持久化（作业评分项 10 分）")
            status, body = request("GET", "/api/history")
            check("GET /api/history 返回 200", status, 200)
            items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            check("历史里有记录", len(items) > 0, True)

            if not items:
                # ★ 前置条件不满足时给出明确提示，而不是继续往下跑然后抛 IndexError。
                #   最常见的原因就是 parser.py 里的 TODO 还没填 —— 计算全失败，
                #   所以一条历史都没写进数据库（这是设计使然：失败不写库）。
                print("\n" + "!" * 62)
                print("后续用例无法继续：历史表是空的。")
                print("最可能的原因：表达式解析还没实现（src/calculator/parser.py 里有 TODO）。")
                print("计算失败时不会写历史，所以历史必然是空的。")
                print("请先把 parser.py 的 _parse_expression 和 _parse_term 实现，再跑本脚本。")
                print("!" * 62)
                return _report()

            check("最新的记录在最前面", items[0].get("expression"), "2*(3+(4-1))")
            check(
                "记录含 id/expression/result/createdAt 四个字段",
                sorted(items[0].keys()),
                ["createdAt", "expression", "id", "result"],
            )

            status, body = request("GET", "/api/history?keyword=12")
            found = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            check("按关键字搜索", [x["expression"] for x in found], ["12+8"])

            count_before = len(items)

            # ------------------------------------------------------ ④ 删除记录
            print("\n[5] 删除指定记录（作业评分项 10 分）")
            target_id = items[0]["id"]
            other_id = items[1]["id"]

            status, _ = request("DELETE", f"/api/history/{target_id}")
            check("删除已存在的记录返回 204", status, 204)

            status, body = request("GET", "/api/history")
            after = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            remaining_ids = [x["id"] for x in after]
            check("被删的记录确实没了", target_id in remaining_ids, False)
            check("其它记录不受影响", other_id in remaining_ids, True)
            check("总数少了一条", len(after), count_before - 1)

            status, body = request("DELETE", "/api/history/999999")
            check("删除不存在的记录返回 404", status, 404)
            check("错误码正确", body.get("errorCode") if isinstance(body, dict) else None, "RECORD_NOT_FOUND")

            # ------------------------------------------------------ 扩展接口
            print("\n[6] 扩展接口")
            status, body = request("GET", "/api/stats")
            check("GET /api/stats 返回 200", status, 200)

            status, _ = request("DELETE", "/api/history")
            check("DELETE /api/history 清空返回 200", status, 200)
            status, body = request("GET", "/api/history")
            check("清空后没有记录", body.get("data", {}).get("items", []), [])

            # ------------------------------------------------------ ★ 持久化验证
            print("\n[7] ★ 持久化验证：重启服务后历史还在")
            request("POST", "/api/calculate", {"expression": "7*6"})

            proc.terminate()
            proc.wait(timeout=10)
            print("  服务已停止")

            proc = subprocess.Popen(
                [sys.executable, "run.py", "--port", str(PORT), "--db", str(db_path)],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if not wait_for_server():
                print("  重启失败")
                return 2
            print("  服务已重启（用的是同一个数据库文件）")

            status, body = request("GET", "/api/history")
            items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            check("重启后历史依然存在", [x["expression"] for x in items], ["7*6"])
            check("重启后计算结果也对", items[0]["result"] if items else None, "42")

            # ------------------------------------------------------ 表里分离
            print("\n[8] 表达式原样保留（后端按 ASCII 解析）")
            status, body = request("POST", "/api/calculate", {"expression": "12+8"})
            check(
                "返回的 expression 与请求一致",
                body.get("data", {}).get("expression") if isinstance(body, dict) else None,
                "12+8",
            )

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()

    # ---------------------------------------------------------------- 汇总
    return _report()


def _report() -> int:
    """输出汇总并返回退出码。"""
    total = passed + len(failures)
    print("\n" + "=" * 62)
    if not failures:
        print(f"黑盒验收全部通过：{passed}/{total}")
        print("=" * 62)
        return 0

    print(f"黑盒验收失败 {len(failures)} 项（共 {total}）：")
    for item in failures:
        print(f"  ✗ {item}")
    print("=" * 62)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
