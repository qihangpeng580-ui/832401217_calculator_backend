"""后端服务入口。

启动方式（在项目根目录下）：
    py -3.12 run.py                      # 默认 127.0.0.1:8000
    py -3.12 run.py --port 8080          # 换端口
    py -3.12 run.py --host 0.0.0.0       # 允许局域网/公网访问（配合内网穿透时用）

首次运行会自动建数据库文件（默认在 data/calculator.db）。

------------------------------------------------------------------
为什么用 http.server 而不用 Flask / FastAPI
------------------------------------------------------------------

    1. 作业帖明确允许"其它合理的技术方案"，不强制框架；
    2. http.server 和 sqlite3 都是 Python 标准库 —— **零依赖**，
       助教拿到代码后不需要 pip install 任何东西就能跑起来；
    3. 这个后端只有 6 个接口，路由用几个 if 就够清楚，
       引入框架主要是多一层需要理解的东西。

    代价：需要自己处理一些框架本来会做的事情（比如解析请求体、拼 CORS 头）。
    这些代码都在 http_controller.py 里，一共几十行，且都写了注释。
"""

from __future__ import annotations

import argparse
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# 让 "from src.xxx import ..." 在直接运行 run.py 时也能工作。
# （直接运行脚本时，Python 默认只把脚本所在目录加进搜索路径，
#   而这个项目用的是 src 包结构，所以要手动把项目根目录加进去。）
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.controller.http_controller import CalculatorRequestHandler  # noqa: E402
from src.service.history_service import HistoryService  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_DB = PROJECT_ROOT / "data" / "calculator.db"


def _make_console_robust() -> None:
    """让标准输出/错误在编码不匹配时不要崩溃。

    ★ 为什么需要这一步：
       这份代码里有很多中文（提示信息、注释里提到、异常路径里）。
       当服务的输出被重定向到管道时（例如被测试脚本用 subprocess.Popen 启动），
       Windows 上管道的默认编码可能是 GBK。
       此时打印中文路径的异常堆栈会抛 UnicodeEncodeError ——
       而这个异常发生在异常处理块内部，会把本该发出的 500 响应也带走，
       客户端只看到"连接被切断"，真实原因完全看不到（踩过这个坑）。

       把 errors 设为 "replace"：无法编码的字符替换成 '?'，绝不抛异常。
    """
    import sys

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - 改不了就算了，不影响功能
                pass


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="前后端分离计算器 —— 后端服务",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  py -3.12 run.py                      在 127.0.0.1:8000 启动\n"
            "  py -3.12 run.py --port 8080          换端口\n"
            "  py -3.12 run.py --host 0.0.0.0       允许外部访问\n"
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"数据库文件路径（默认 {DEFAULT_DB}）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动服务。"""
    _make_console_robust()
    args = build_parser().parse_args(argv)

    # 1) 准备服务对象并建表
    service = HistoryService(args.db)
    service.init()

    # 2) 把 service 挂到 Handler 类上。
    #
    #    为什么挂在类上而不是每个请求新建：
    #        BaseHTTPRequestHandler 每个请求会新建一个实例，
    #        service 是无状态的（每次操作自己开数据库连接），所以可以安全共享。
    #        如果用实例属性，就得在 __init__ 里传参，而 http.server 不允许改签名。
    CalculatorRequestHandler.service = service

    # 3) 启动多线程 HTTP 服务。
    #
    #    ThreadingHTTPServer（而不是 HTTPServer）：
    #    前者为每个请求开一个线程。单线程的服务在同时有两个请求时会排队，
    #    而浏览器的预检请求（OPTIONS）+ 真实请求就是并发的，
    #    用单线程容易卡住。
    server = ThreadingHTTPServer((args.host, args.port), CalculatorRequestHandler)

    db_display = Path(args.db)
    print("=" * 62)
    print("  前后端分离计算器 —— 后端服务已启动")
    print("=" * 62)
    print(f"  监听地址   http://{args.host}:{args.port}")
    print(f"  健康检查   http://{args.host}:{args.port}/api/health")
    print(f"  数据库     {db_display}")
    print("  接口列表")
    print("    POST   /api/calculate         计算（结果由本服务产生）")
    print("    GET    /api/history           查询历史")
    print("    DELETE /api/history/{id}      删除一条历史")
    print("    DELETE /api/history           清空历史")
    print("    GET    /api/stats             统计信息")
    print("    GET    /api/health            健康检查")
    print("-" * 62)
    print("  按 Ctrl+C 停止服务")
    print("=" * 62)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭服务 ...")
    finally:
        server.server_close()
        print("服务已停止")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
