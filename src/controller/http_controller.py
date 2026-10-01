"""HTTP interface layer -- translates requests into service calls and results into JSON.

Responsibility boundary (important):
    This module **only translates**: it parses the request body, picks out the
    parameters, calls the service and turns a result or an exception into a
    response. It does **not** validate expressions (that is the calculator layer),
    make business decisions (the service layer) or write SQL (the model layer).

The benefit of that split: replacing the HTTP framework (with FastAPI, say) means
rewriting this one file, with not a single line changed anywhere else.

------------------------------------------------------------------
Endpoint overview
------------------------------------------------------------------

    POST   /api/calculate          calculate and save to history
    GET    /api/history            query history (supports keyword / limit)
    DELETE /api/history/{id}       delete one history record
    DELETE /api/history            clear all history (extended feature)
    GET    /api/stats              statistics (extended feature)
    GET    /api/health             health check (liveness for deployment, used by the
                                   teaching assistant to verify reachability)
    OPTIONS *                      cross-origin preflight

    GET    /                       front-end page (optional, see below)
    GET    /css/... /js/... etc.   front-end static assets (optional)

------------------------------------------------------------------
Optional capability: hosting the front-end page as well
------------------------------------------------------------------

Starting with `--frontend-dir <dir>` (see run.py) makes this service serve the
front-end page from the same port too. That has one very practical benefit for
this assignment:

    The teacher or teaching assistant needs **a single link** to test and grade.
    Something like http://<server-ip>:8000/ -- open it and the calculator is
    there; press = and it computes.

Compare the alternative (front-end on GitHub Pages + back-end on a server):
    - Two addresses have to be opened before you know which is which;
    - The front-end calls the back-end **cross-origin**, adding one more thing
      that can go wrong;
    - A teaching assistant on a restricted network may be unable to open GitHub Pages.

When page and API are served from the same port:
    - One link is enough and it works as soon as it is opened;
    - Page and API are **same-origin**, so cross-origin problems cannot arise
      (the front-end simply sets API_BASE_URL to '').

Note: this module provides that static-file capability for **local/assignment
demonstrations** only. In production, static assets should be served by a
dedicated static server such as Nginx.

------------------------------------------------------------------
Uniform response format
------------------------------------------------------------------

Success:
    {"success": true, "data": {...}}

Failure:
    {"success": false, "errorCode": "INVALID_EXPRESSION", "message": "..."}

Why the error code sits at the top level instead of inside data:
    showServerError(errorCode) in the front-end ui.js reads errorCode directly to
    look up the message table, so the front-end can handle errors without
    understanding the shape of data.
"""

from __future__ import annotations

import json
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from src.common.errors import BadRequestError, CalcError
from src.service.history_service import HistoryService

# Path for deleting a single history record: /api/history/123
HISTORY_ID_PATTERN = re.compile(r"^/api/history/(\d+)$")

# How many history records are returned by default
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200

# Request body size limit. Keeps a multi-hundred-MB body from blowing up the service.
MAX_BODY_BYTES = 64 * 1024

# MIME types for static assets (only needed when hosting the front-end)
STATIC_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


class CalculatorRequestHandler(BaseHTTPRequestHandler):
    """Handle every HTTP request for the calculator.

    The instance attribute ``service`` is attached to the class at start-up
    (see the notes in main.py).
    """

    # Injected by main.py
    service: HistoryService

    # Front-end static file directory, injected by run.py at start-up; None means
    # the front-end page is not hosted.
    frontend_dir: Path | None = None

    # Server identification (appears in the Server response header)
    server_version = "CalculatorBackend/1.0"

    # Silence the default "print one line per request" log noise.
    # A trimmed log is kept instead (see log_message) to make troubleshooting easier.
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    # ================================================================ entry dispatch

    def do_OPTIONS(self) -> None:  # noqa: N802  (method name required by BaseHTTPRequestHandler)
        """Cross-origin preflight.

        When the front-end is deployed on another domain (GitHub Pages, say) the
        browser first sends OPTIONS to ask "may I call this API?". The answer has
        to be correct, otherwise the real request is never sent at all.
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
        """Single exception safety net.

        Every business method enters through here, which means the try/except is
        written **only once**: any CalcError is translated into its HTTP status
        code plus error code, and any other exception becomes a 500 with a printed
        traceback (for debugging) that never leaks to the front-end.
        """
        path = self.path.split("?", 1)[0]

        try:
            self._route(method, path)
        except CalcError as exc:
            # Business error: the exception carries both the status code and the error code
            self._send_error(exc.http_status, exc.error_code, exc.message)
        except Exception:  # noqa: BLE001 - the safety net must catch everything
            # Unexpected error: print the traceback for ourselves, return only a generic error
            self._print_traceback_safely()
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Internal server error, please try again later",
            )

    @staticmethod
    def _print_traceback_safely() -> None:
        """Print the exception traceback, but **never let the printing itself break the response**.

        There is a hard-to-diagnose problem here:
           traceback.print_exc() writes to sys.stderr by default. When the
           service's output is redirected into a pipe (started by another script
           with subprocess.Popen, say) the pipe encoding may be GBK while the
           traceback contains Chinese path names -- so print_exc itself raises
           UnicodeEncodeError. That exception happens inside the except block and
           takes the pending 500 response down with it: the client only sees
           "connection closed" and never learns the real cause.

        Two defences:
            1. The printing is wrapped in try/except: if it fails, so be it, the
               response still has to go out;
            2. The text is formatted into a string first and written with
               errors="replace", so characters that cannot be encoded become '?'
               instead of raising.
        """
        import sys

        try:
            text = traceback.format_exc()
            stream = sys.stderr
            # Write with the replace mode where possible; failing to write must not
            # affect the response
            try:
                stream.write(text)
                stream.flush()
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
                stream.write(safe)
                stream.flush()
        except Exception:  # noqa: BLE001 - a failed print must never affect the response
            pass

    def _route(self, method: str, path: str) -> None:
        """Routing table. A plain if chain, no framework."""
        # ---- Paths starting with /api/ go to the API ----
        if path.startswith("/api/"):
            self._route_api(method, path)
            return

        # ---- Other paths are tried as static assets (when hosting the front-end page) ----
        if method == "GET" and self._serve_static(path):
            return

        # Nothing matched
        self._send_error(
            HTTPStatus.NOT_FOUND,
            "RECORD_NOT_FOUND",
            f"No such endpoint: {method} {path}",
        )

    def _route_api(self, method: str, path: str) -> None:
        """API routing."""
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

        self._send_error(
            HTTPStatus.NOT_FOUND,
            "RECORD_NOT_FOUND",
            f"No such endpoint: {method} {path}",
        )

    def _serve_static(self, path: str) -> bool:
        """Try to serve a path as a static file.

        Returns:
            True means it was handled and a response was sent; False means it was
            not found (the caller replies 404).

        Security: one vulnerability must be prevented here -- **directory traversal**.
          Concatenating the user-supplied path onto the directory would let a
          request for `/../../../etc/passwd` read system files.
          The defence is to resolve the concatenation to an absolute path and
          then confirm it is **still inside** the static directory.
          (Path.is_relative_to from Python 3.9+ does exactly this.)
        """
        if self.frontend_dir is None:
            return False

        # Strip the leading slash; an empty path means index.html
        relative = path.lstrip("/") or "index.html"

        # A directory-style request (ending in /) also means index.html in that directory
        if relative.endswith("/"):
            relative += "index.html"

        try:
            # The effect of decodeURIComponent: turn percent-encoded non-ASCII
            # sequences such as %E5%A5%B6 back into characters
            from urllib.parse import unquote

            relative = unquote(relative)
        except Exception:  # noqa: BLE001
            return False

        # Reject any path containing .. (first line of defence)
        if ".." in relative.split("/"):
            return False

        candidate = (self.frontend_dir / relative).resolve()

        # Second line of defence: the resolved real path must still be inside the
        # static directory (this blocks subtler bypasses such as symbolic links)
        try:
            if not candidate.is_relative_to(self.frontend_dir.resolve()):
                return False
        except (ValueError, OSError):
            return False

        if not candidate.is_file():
            return False

        try:
            content = candidate.read_bytes()
        except OSError:
            return False

        content_type = STATIC_MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        # Static assets may be cached briefly: loading the page requests a dozen
        # files, and without caching every refresh resends them all. The window is
        # kept short so a change shows up immediately.
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("X-Served-By", "calculator-backend-static")
        self.end_headers()
        self.wfile.write(content)
        return True

    # ================================================================ endpoint implementations

    def _handle_health(self) -> None:
        """Health check.

        The assignment requires "deploy and verify reachability", so the teaching
        assistant can open this address to confirm the service is alive. It returns
        a minimal JSON body and never queries the database, so it always answers
        instantly.
        """
        self._send_json(
            HTTPStatus.OK,
            {
                "success": True,
                "data": {
                    "status": "ok",
                    "service": "calculator-backend",
                    "note": "Back-end service is running; the front end does not "
                            "take part in calculations",
                },
            },
        )

    def _handle_calculate(self) -> None:
        """POST /api/calculate -- the core endpoint.

        Request body:   {"expression": "12+8"}
        Response body:  {"success": true, "data": {"expression": "12+8",
                         "result": "20", "resultNumber": 20.0}}
        """
        body = self._read_json_body()
        expression = body.get("expression")

        if expression is None:
            raise BadRequestError("Request body is missing the expression field")
        if not isinstance(expression, str):
            raise BadRequestError("Expression must be a string")

        outcome = self.service.calculate_and_save(expression)

        # result is provided in two forms:
        #   result       a string that keeps decimal precision (for display, and so
        #                that 0.3 is not turned into 0.2999...)
        #   resultNumber a number, ready for direct use when the front-end needs
        #                to do numeric work
        #
        # Why not only a number: JSON numbers carry no precision guarantee. In
        # client-side JavaScript JSON.parse("0.3") is fine, but a non-terminating
        # decimal such as "1/3" can only be sent as a string.
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
                raise BadRequestError("limit must be an integer") from exc
            if limit <= 0:
                raise BadRequestError("limit must be greater than 0")
            # Cap the limit so a single request cannot pull so much that memory fills up
            limit = min(limit, MAX_HISTORY_LIMIT)

        keyword = query.get("keyword") or None

        data = self.service.list_history(limit=limit, keyword=keyword)
        self._send_json(HTTPStatus.OK, {"success": True, "data": data})

    def _handle_history_delete(self, record_id: int) -> None:
        """DELETE /api/history/{id}

        Success returns 204 (no body, matching HTTP semantics); when the id does
        not exist the service raises RecordNotFoundError and the safety net in
        _dispatch replies 404.
        """
        self.service.delete_history(record_id)
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_history_clear(self) -> None:
        """DELETE /api/history -- clear everything (extended feature)."""
        deleted = self.service.delete_all_history()
        self._send_json(
            HTTPStatus.OK,
            {"success": True, "data": {"deleted": deleted}},
        )

    def _handle_stats(self) -> None:
        """GET /api/stats -- statistics (extended feature)."""
        self._send_json(HTTPStatus.OK, {"success": True, "data": self.service.stats()})

    # ================================================================ request parsing

    def _read_json_body(self) -> dict:
        """Read and parse the JSON request body."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise BadRequestError("Invalid Content-Length") from exc

        if length <= 0:
            raise BadRequestError("Request body cannot be empty")

        if length > MAX_BODY_BYTES:
            raise BadRequestError(f"Request body is too large, at most {MAX_BODY_BYTES} bytes")

        raw = self.rfile.read(length)

        # Decoding must be explicitly utf-8.
        # The default is the system encoding (GBK on a Chinese Windows install),
        # which garbles any non-ASCII characters in the expression.
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BadRequestError("Request body must be UTF-8 encoded") from exc

        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"Request body is not valid JSON: {exc.msg}") from exc

        if not isinstance(body, dict):
            raise BadRequestError("Request body must be a JSON object")

        return body

    def _parse_query(self) -> dict:
        """Parse the query string.

        A minimal implementation is used rather than urllib.parse: the cases that
        need handling are simple, and this way '+' is handled properly as well (in
        a query string '+' means a space, but a keyword may genuinely be searching
        for the '+' operator).
        """
        if "?" not in self.path:
            return {}

        from urllib.parse import parse_qs

        raw_query = self.path.split("?", 1)[1]
        # keep_blank_values=False: ignore empty parameters
        # Note that parse_qs turns "+" into a space, which affects keyword search.
        #   To search for the operator itself the front-end should send the
        #   URL-encoded "%2B".
        parsed = parse_qs(raw_query, keep_blank_values=False)
        return {key: values[0] for key, values in parsed.items() if values}

    # ================================================================ response output

    def _send_cors_headers(self) -> None:
        """Cross-origin headers.

        Why * (allow any origin):
            The front-end may be deployed on GitHub Pages, or may simply be opened
            from a local file:// URL, so its address is not known in advance.
            Wide-open CORS is reasonable in an assignment setting.
            (In production this should be an allowlist, as noted in the README.)
        """
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        """Write a JSON response."""
        # ensure_ascii=False emits non-ASCII characters directly (rather than as
        # \uXXXX): it saves bandwidth and is easier to read, and the front-end
        # JSON.parse accepts either form.
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Content-Length must be the **byte count**, not the character count.
        #   A CJK character takes 3 bytes, so len(str) would be wrong and the
        #   browser would keep waiting for data that never arrives.
        self.send_header("Content-Length", str(len(body)))
        # This custom header exists so that a teaching assistant or classmate can
        # verify things: the browser's Network panel shows that the result really
        # came from the back-end.
        self.send_header("X-Calculated-By", "backend")
        self._send_cors_headers()
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, error_code: str, message: str) -> None:
        """Write an error response."""
        self._send_json(
            status,
            {"success": False, "errorCode": error_code, "message": message},
        )
