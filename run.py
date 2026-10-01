"""Back end service entry point.

How to start it (from the project root):
    py -3.12 run.py                      # default 127.0.0.1:8000
    py -3.12 run.py --port 8080          # use another port
    py -3.12 run.py --host 0.0.0.0       # allow LAN/public access (used with port forwarding)

The database file is created automatically on the first run (data/calculator.db by default).

------------------------------------------------------------------
Why http.server instead of Flask / FastAPI
------------------------------------------------------------------

    1. The assignment post allows "other reasonable technical solutions", no framework is mandated;
    2. http.server and sqlite3 both ship with the Python standard library -- **zero dependencies**,
       so the teaching assistant can run the code without installing anything with pip;
    3. This back end has only 6 endpoints and a few if statements keep the routing clear,
       and adopting a framework would mainly add one more layer to understand.

    The cost: some things a framework would normally do must be handled here -- parsing the
    request body, assembling the CORS headers. That code is in http_controller.py and is commented.
"""

from __future__ import annotations

import argparse
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# Make "from src.xxx import ..." work when run.py is executed directly -- running
# a script directly makes Python add only the script's directory to the search path, but
# this project uses a src package layout, so the project root has to be added by hand.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.controller.http_controller import CalculatorRequestHandler  # noqa: E402
from src.service.history_service import HistoryService  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_DB = PROJECT_ROOT / "data" / "calculator.db"


def _make_console_robust() -> None:
    """Keep standard output/error from crashing when the encoding does not match.

    Why this step is needed:
       The output can contain non-ASCII characters (the project path in a traceback, say).
       When the service's output is redirected into a pipe (started by a test script with
       subprocess.Popen, for example), the pipe's default encoding on Windows may be GBK.
       Printing an exception traceback that contains such a path then raises UnicodeEncodeError --
       and that exception happens inside the exception handling block, so it takes the 500
       response with it: the client only sees "the connection was cut" and never the real cause.

       Setting errors to "replace": characters that cannot be encoded become '?',
       never an exception.
    """
    import sys

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - if it fails, so be it; functionality is unaffected
                pass


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Front-end/back-end separated calculator -- back-end service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  py -3.12 run.py                      start on 127.0.0.1:8000\n"
            "  py -3.12 run.py --port 8080          use another port\n"
            "  py -3.12 run.py --host 0.0.0.0       allow external access\n"
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"listen address (default {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"listen port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"database file path (default {DEFAULT_DB})",
    )
    parser.add_argument(
        "--frontend-dir",
        default=None,
        help=(
            "Optional. Give the directory holding the front-end page and this service will "
            "serve it on the same port, so teacher/TA needs one link and sees the calculator."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Start the service."""
    _make_console_robust()
    args = build_parser().parse_args(argv)

    # 1) Prepare the service object and create the table
    service = HistoryService(args.db)
    service.init()

    # 2) Attach service to the Handler class.
    #
    #    Why attach it to the class instead of creating one per request:
    #        BaseHTTPRequestHandler creates a new instance for every request,
    #        service is stateless (each operation opens its own db connection), so sharing is safe.
    #        An instance attribute would need __init__ parameters, which http.server forbids.
    CalculatorRequestHandler.service = service

    # 2.5) Optional: host the front-end page.
    #
    #      With --frontend-dir, this service also serves the front-end page from the same port.
    #      That way the teacher/TA **needs only one link**:
    #          http://<server-ip>:8000/     <- open it and it is the calculator
    #      Page and API are also same-origin, so cross-origin problems cannot arise.
    frontend_dir = None
    if args.frontend_dir:
        candidate = Path(args.frontend_dir).resolve()
        if not (candidate / "index.html").is_file():
            print(f"the directory given to --frontend-dir has no index.html: {candidate}")
            print("  Check that the path is correct. The front-end page will not be hosted.")
        else:
            frontend_dir = candidate
            CalculatorRequestHandler.frontend_dir = frontend_dir

    # 3) Start the multi-threaded HTTP service.
    #
    #    ThreadingHTTPServer (rather than HTTPServer):
    #    the former opens a thread per request. A single-threaded service queues when two
    #    requests arrive at once, and the browser's preflight request (OPTIONS) plus the real
    #    request are exactly that, so a single-threaded server easily gets stuck.
    server = ThreadingHTTPServer((args.host, args.port), CalculatorRequestHandler)

    db_display = Path(args.db)
    print("=" * 62)
    print("  Front-end/back-end separated calculator -- back-end service started")
    print("=" * 62)
    print(f"  Listening on   http://{args.host}:{args.port}")
    print(f"  Health check   http://{args.host}:{args.port}/api/health")
    print(f"  Database       {db_display}")
    if frontend_dir:
        print(
            f"  Front end      http://{args.host}:{args.port}/   "
            f"<- open it and it is the calculator"
        )
        print(f"                 (source: {frontend_dir})")
    else:
        print("  Front end      not hosted (add --frontend-dir <dir> to serve the page too)")
    print("  Endpoints")
    print("    POST   /api/calculate         calculate (the result is produced by this service)")
    print("    GET    /api/history           query history")
    print("    DELETE /api/history/{id}      delete one history record")
    print("    DELETE /api/history           clear history")
    print("    GET    /api/stats             statistics")
    print("    GET    /api/health            health check")
    print("-" * 62)
    print("  Press Ctrl+C to stop the service")
    print("=" * 62)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStop signal received, shutting down the service ...")
    finally:
        server.server_close()
        print("Service stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
