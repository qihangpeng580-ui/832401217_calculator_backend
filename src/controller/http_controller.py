"""HTTP 接口层 —— 把请求翻译成对 service 的调用，再把结果翻译成 JSON。

职责边界（很重要）：
    本模块**只做翻译**：解析请求体、挑出参数、调 service、把结果或异常变成响应。
    它**不做**：表达式校验（在 calculator 层）、业务判断（在 service 层）、SQL（在 model 层）。

这样划分的好处：换掉 HTTP 框架（比如以后改成 FastAPI）时，
只需要重写这一个文件，其余代码一行都不用动。

------------------------------------------------------------------
接口一览
------------------------------------------------------------------

    POST   /api/calculate          计算并保存历史
    GET    /api/history            查询历史（支持 keyword / limit）
    DELETE /api/history/{id}       删除一条历史
    DELETE /api/history            清空全部历史（扩展功能）
    GET    /api/stats              统计信息（扩展功能）
    GET    /api/health             健康检查（部署探活，助教验证可访问性用）
    OPTIONS *                      跨域预检

------------------------------------------------------------------
统一响应格式
------------------------------------------------------------------

成功：
    {"success": true, "data": {...}}

失败：
    {"success": false, "errorCode": "INVALID_EXPRESSION", "message": "..."}

为什么把错误码单独放在顶层而不是塞进 data：
    前端 ui.js 里的 showServerError(errorCode) 直接读 errorCode 查中文提示表，
    这样前端不需要理解 data 的形状就能处理错误。
"""

from __future__ import annotations

import json
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from src.common.errors import BadRequestError, CalcError
from src.service.history_service import HistoryService

# 删除单条历史的路径：/api/history/123
HISTORY_ID_PATTERN = re.compile(r"^/api/history/(\d+)$")

# 默认返回多少条历史
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200

# 请求体大小上限。防止有人发一个几百 MB 的 body 把服务撑爆。
MAX_BODY_BYTES = 64 * 1024


class CalculatorRequestHandler(BaseHTTPRequestHandler):
    """处理计算器的所有 HTTP 请求。

    实例属性 ``service`` 由 main.py 在启动时挂到类上（见 main.py 的说明）。
    """

    # 由 main.py 注入
    service: HistoryService

    # 服务器标识（会出现在 Server 响应头里）
    server_version = "CalculatorBackend/1.0"

    # 关闭默认的"每来一个请求就打印一行"的日志噪声。
    # 保留一份精简日志（见 log_message），便于排查问题。
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    # ================================================================ 入口分派

    def do_OPTIONS(self) -> None:  # noqa: N802  （BaseHTTPRequestHandler 规定的方法名）
        """跨域预检。

        前端部署在别的域名（比如 GitHub Pages）时，浏览器会先发 OPTIONS 问一句
        "我能不能调这个接口"。必须正确回话，否则真实请求根本不会发出。
        """
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        """统一的异常兜底。

        所有业务方法都从这里进来，好处是**只需要写一次 try/except**：
        任何 CalcError 都会被翻译成对应的 HTTP 状态码 + 错误码，
        任何其它异常都会变成 500 并打印堆栈（便于查错），但不会泄漏给前端。
        """
        path = self.path.split("?", 1)[0]

        try:
            self._route(method, path)
        except CalcError as exc:
            # 业务错误：状态码和错误码都由异常自己带着
            self._send_error(exc.http_status, exc.error_code, exc.message)
        except Exception:  # noqa: BLE001 - 兜底必须捕获所有异常
            # 非预期错误：打印堆栈给自己看，但只回一个通用错误给前端
            self._print_traceback_safely()
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "服务器内部错误，请稍后再试",
            )

    @staticmethod
    def _print_traceback_safely() -> None:
        """打印异常堆栈，但**绝不因为打印本身失败而中断响应**。

        ★ 这里踩过一个很难查的坑：
           traceback.print_exc() 默认写到 sys.stderr。当服务的输出被重定向到管道时
           （比如被另一个脚本用 subprocess.Popen 启动），管道的编码可能是 GBK，
           而堆栈里含有中文路径 —— 于是 print_exc 自己抛 UnicodeEncodeError。
           那个异常发生在 except 块内部，会把原本要发的 500 响应也一起带走，
           客户端只看到"连接被切断"，完全看不到真实原因。

        两处防御：
            1. 打印包在 try/except 里，打印失败就算了，响应必须发出去；
            2. 先把内容格式化成字符串再用 errors="replace" 输出，
               遇到无法编码的字符替换成 '?' 而不是抛异常。
        """
        import sys

        try:
            text = traceback.format_exc()
            stream = sys.stderr
            # 尽量用 replace 模式写，写不进去也不影响响应
            try:
                stream.write(text)
                stream.flush()
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe)
                stream.flush()
        except Exception:  # noqa: BLE001 - 打印失败绝不能影响响应
            pass

    def _route(self, method: str, path: str) -> None:
        """路由表。用简单的 if 链，不引入框架。"""
        if method == "GET" and path == "/api/health":
            self._handle_health()
            return

        if method == "GET" and path == "/api/history":
            self._handle_history_list()
            return

        if method == "GET" and path == "/api/stats":
            self._handle_stats()
            return

        if method == "POST" and path == "/api/calculate":
            self._handle_calculate()
            return

        if method == "DELETE" and path == "/api/history":
            self._handle_history_clear()
            return

        match = HISTORY_ID_PATTERN.match(path)
        if method == "DELETE" and match:
            self._handle_history_delete(int(match.group(1)))
            return

        # 没匹配上任何路由
        self._send_error(HTTPStatus.NOT_FOUND, "RECORD_NOT_FOUND", f"接口不存在：{method} {path}")

    # ================================================================ 各接口实现

    def _handle_health(self) -> None:
        """健康检查。

        作业要求「部署并验证可访问性」，助教可以直接打开这个地址确认服务活着。
        只回一句极简的 JSON，不查数据库，保证永远秒回。
        """
        self._send_json(
            HTTPStatus.OK,
            {
                "success": True,
                "data": {
                    "status": "ok",
                    "service": "calculator-backend",
                    "note": "后端服务运行中；计算由本服务完成，前端不参与计算",
                },
            },
        )

    def _handle_calculate(self) -> None:
        """POST /api/calculate —— 核心接口。

        请求体：  {"expression": "12+8"}
        响应体：  {"success": true, "data": {"expression": "12+8", "result": "20", "resultNumber": 20}}
        """
        body = self._read_json_body()
        expression = body.get("expression")

        if expression is None:
            raise BadRequestError("请求体缺少 expression 字段")
        if not isinstance(expression, str):
            raise BadRequestError("expression 必须是字符串")

        outcome = self.service.calculate_and_save(expression)

        # result 同时给两种形式：
        #   result       字符串，保留十进制精度（前端显示用，也便于保存 0.3 不被变成 0.2999...）
        #   resultNumber 数字，方便前端需要做数值处理时直接用
        #
        # 为什么不只给数字：JSON 的数字没有精度保证，
        # 客户端 JavaScript 里 JSON.parse("0.3") 是没问题的，
        # 但 "1/3" 这种无限小数只能给字符串。
        payload = {
            "expression": outcome.expression,
            "result": outcome.result,
            "resultNumber": float(outcome.value),
        }

        self._send_json(HTTPStatus.OK, {"success": True, "data": payload})

    def _handle_history_list(self) -> None:
        """GET /api/history?limit=50&keyword=12+"""
        query = self._parse_query()

        limit = DEFAULT_HISTORY_LIMIT
        raw_limit = query.get("limit")
        if raw_limit:
            try:
                limit = int(raw_limit)
            except ValueError as exc:
                raise BadRequestError("limit 必须是整数") from exc
            if limit <= 0:
                raise BadRequestError("limit 必须大于 0")
            # 限制上限，防止一次拉太多把内存吃满
            limit = min(limit, MAX_HISTORY_LIMIT)

        keyword = query.get("keyword") or None

        data = self.service.list_history(limit=limit, keyword=keyword)
        self._send_json(HTTPStatus.OK, {"success": True, "data": data})

    def _handle_history_delete(self, record_id: int) -> None:
        """DELETE /api/history/{id}

        成功回 204（无响应体，符合 HTTP 语义）；
        id 不存在时 service 会抛 RecordNotFoundError，由 _dispatch 兜底回 404。
        """
        self.service.delete_history(record_id)
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_history_clear(self) -> None:
        """DELETE /api/history —— 清空全部（扩展功能）。"""
        deleted = self.service.delete_all_history()
        self._send_json(
            HTTPStatus.OK,
            {"success": True, "data": {"deleted": deleted}},
        )

    def _handle_stats(self) -> None:
        """GET /api/stats —— 统计信息（扩展功能）。"""
        self._send_json(HTTPStatus.OK, {"success": True, "data": self.service.stats()})

    # ================================================================ 请求解析

    def _read_json_body(self) -> dict:
        """读取并解析 JSON 请求体。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise BadRequestError("Content-Length 不合法") from exc

        if length <= 0:
            raise BadRequestError("请求体不能为空")

        if length > MAX_BODY_BYTES:
            raise BadRequestError(f"请求体过大，最多 {MAX_BODY_BYTES} 字节")

        raw = self.rfile.read(length)

        # ★ 必须显式用 utf-8 解码。
        # 默认按系统编码解（中文 Windows 上是 GBK），表达式里的中文会乱码。
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BadRequestError("请求体必须是 UTF-8 编码") from exc

        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"请求体不是合法的 JSON：{exc.msg}") from exc

        if not isinstance(body, dict):
            raise BadRequestError("请求体必须是一个 JSON 对象")

        return body

    def _parse_query(self) -> dict:
        """解析查询字符串。

        用一个极简的实现而不用 urllib.parse：需要处理的情况很简单，
        而且这样能顺手把 '+' 正确处理（在查询串里 '+' 表示空格，
        但我们的 keyword 可能真的想搜 '+' 运算符）。
        """
        if "?" not in self.path:
            return {}

        from urllib.parse import parse_qs

        raw_query = self.path.split("?", 1)[1]
        # keep_blank_values=False：忽略空参数
        # ★ 注意 parse_qs 会把 "+" 变成空格，这对 keyword 搜索有影响。
        #   前端如果真的要搜运算符，应该传 URL 编码后的 "%2B"。
        parsed = parse_qs(raw_query, keep_blank_values=False)
        return {key: values[0] for key, values in parsed.items() if values}

    # ================================================================ 响应输出

    def _send_cors_headers(self) -> None:
        """跨域头。

        为什么要用 *（允许任何来源）：
            前端可能部署在 GitHub Pages、也可能就是本机的 file://，
            地址事先不确定。作业场景下开放跨域是合理的。
            （生产环境应该改成白名单，这一点写进 README 说明。）
        """
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        """输出 JSON 响应。"""
        # ensure_ascii=False 让中文直接输出（不转成 \uXXXX），
        # 既省带宽也更易读；前端 JSON.parse 两种都能吃。
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # ★ Content-Length 必须是**字节数**，不是字符数。
        #   中文一个字 3 字节，用 len(str) 会算错，导致浏览器一直等剩下的数据。
        self.send_header("Content-Length", str(len(body)))
        # 这个自定义头是给助教/同学验证用的：
        # 打开浏览器 Network 面板就能看到结果确实来自后端。
        self.send_header("X-Calculated-By", "backend")
        self._send_cors_headers()
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, error_code: str, message: str) -> None:
        """输出错误响应。"""
        self._send_json(
            status,
            {"success": False, "errorCode": error_code, "message": message},
        )
