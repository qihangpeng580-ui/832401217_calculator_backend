"""Black-box acceptance script -- walks the full flow with real HTTP requests.

Run (from the project root):
    py -3.12 tools/blackbox.py

It does the following:
    1. create an empty database in a temporary directory and start a real backend
       service (random port);
    2. send **real HTTP requests** with urllib, verifying all four assignment requirements:
         (1) basic arithmetic (12+8 = 20)
         (2) compound expressions (precedence, parentheses, unary sign, decimals,
            invalid expressions, division by zero)
         (3) history persistence (visible right after calculating; **still there**
            after a service restart)
         (4) deleting a specific record (really gone afterwards, the rest untouched)
    3. stop the service and delete the temporary files.

Why this script exists (instead of unit tests alone):
    Unit tests "call the functions directly" and bypass the HTTP layer, but the
    assignment deliverable is a **service reachable over the network** -- so at
    least one test must "really call it over the network", otherwise you get "every
    function correct, yet the service will not start" (the file:// trap).
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
    """Keep draining the child process output so a full pipe buffer cannot wedge it.

    What is read goes into sink and is printed only when something needs debugging.
    """
    if proc.stdout is None:
        return
    for line in proc.stdout:
        sink.append(line)


def check(name: str, actual: object, expected: object) -> None:
    """Assert and record; does not raise, reports once after every case has run."""
    global passed
    if actual == expected:
        passed += 1
        print(f"  OK   {name}")
    else:
        failures.append(f"{name}\n         expected: {expected!r}\n         actual:   {actual!r}")
        print(f"  FAIL {name}")


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    """Send one HTTP request and return (status code, response body).

    204 has no response body, so an empty string is returned.
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
        # Reached when the server cuts the connection. Reraise the real exception,
        # otherwise all you see is "Remote end closed connection" with no clue where to look.
        raise RuntimeError(
            f"connection failed for {method} {path}: {type(exc).__name__}: {exc}"
        ) from exc


def wait_for_server(timeout: float = 15.0) -> bool:
    """Wait until the health check answers."""
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
        print("Black-box acceptance: calculator backend over real HTTP requests")
        print("=" * 62)

        # ---------------------------------------------------------- start service
        print("\n[0] start service")
        proc = subprocess.Popen(
            [sys.executable, "run.py", "--port", str(PORT), "--db", str(db_path)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Drain the child process output in the background.
        # It must be read! A PIPE that is never read blocks the child once the pipe
        #   buffer fills up, which shows up as "the service mysteriously hangs". A
        #   thread drains it into memory here and it is printed only if startup fails.
        captured: list[str] = []
        reader = threading.Thread(target=_drain, args=(proc, captured), daemon=True)
        reader.start()

        try:
            if not wait_for_server():
                print("  service failed to start, output follows:")
                if proc.stdout:
                    print(proc.stdout.read())
                return 2
            print(f"  OK   service started: {BASE}")

            # ------------------------------------------------------ health check
            status, body = request("GET", "/api/health")
            check("GET /api/health returns 200", status, 200)

            # ------------------------------------------------------ (1) basic arithmetic
            print("\n[1] basic arithmetic (15 rubric points)")
            for expression, expected in [
                ("12+8", "20"),
                ("9-4", "5"),
                ("5*8", "40"),
                ("10/2", "5"),
            ]:
                status, body = request("POST", "/api/calculate", {"expression": expression})
                actual = (
                    body.get("data", {}).get("result")
                    if isinstance(body, dict) and body.get("success")
                    else f"HTTP {status}"
                )
                check(f"{expression} = {expected}", actual, expected)

            # ------------------------------------------------------ (2) compound expressions
            print("\n[2] compound expressions (15 rubric points)")
            cases = [
                ("1+2*3", "7", "operator precedence"),
                ("(1+2)*3", "9", "parentheses"),
                ("10/2+7", "12", "precedence + division"),
                ("8-3*2", "2", "precedence + subtraction"),
                ("-5+8", "3", "unary minus at the start"),
                ("3*-2", "-6", "unary minus after an operator"),
                ("0.1+0.2", "0.3", "decimal precision (no floating point)"),
                ("100/5/2", "10", "left associativity"),
                ("2*(3+(4-1))", "12", "nested parentheses"),
            ]
            for expression, expected, note in cases:
                status, body = request("POST", "/api/calculate", {"expression": expression})
                got = (
                    body.get("data", {}).get("result")
                    if isinstance(body, dict) and body.get("success")
                    else f"HTTP {status}"
                )
                check(f"{expression} = {expected} ({note})", got, expected)

            print("\n[3] invalid expressions and division by zero (assignment requirement)")
            status, body = request("POST", "/api/calculate", {"expression": "1+2*"})
            check("invalid expression returns 400", status, 400)
            code = body.get("errorCode") if isinstance(body, dict) else None
            check("invalid expression error code", code, "INVALID_EXPRESSION")

            status, body = request("POST", "/api/calculate", {"expression": "(1+2"})
            check("unmatched parenthesis returns 400", status, 400)

            status, body = request("POST", "/api/calculate", {"expression": "1+a"})
            check("illegal character returns 400", status, 400)

            status, body = request("POST", "/api/calculate", {"expression": "10/0"})
            check("division by zero returns 422", status, 422)
            code = body.get("errorCode") if isinstance(body, dict) else None
            check("division by zero error code", code, "DIVISION_BY_ZERO")

            status, body = request("POST", "/api/calculate", {"expression": "__import__('os')"})
            check("code injection is rejected", status, 400)

            status, body = request("POST", "/api/calculate", {})
            check("missing expression field returns 400", status, 400)

            # ------------------------------------------------------ (3) history persistence
            print("\n[4] history persistence (10 rubric points)")
            status, body = request("GET", "/api/history")
            check("GET /api/history returns 200", status, 200)
            items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            check("history has records", len(items) > 0, True)

            if not items:
                # Give a clear message when the precondition is not met, instead of
                #   running on and raising IndexError. An empty history means every
                #   calculation case above **failed** -- by design: a failure stores nothing.
                print("\n" + "!" * 62)
                print("cannot continue with the remaining cases: the history table is empty.")
                print("that means every calculation case above failed.")
                print("scroll up and check why the cases in groups [1]~[3] failed.")
                print("!" * 62)
                return _report()

            check("the newest record comes first", items[0].get("expression"), "2*(3+(4-1))")
            check(
                "record has the four fields id/expression/result/createdAt",
                sorted(items[0].keys()),
                ["createdAt", "expression", "id", "result"],
            )

            status, body = request("GET", "/api/history?keyword=12")
            found = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            check("search by keyword", [x["expression"] for x in found], ["12+8"])

            count_before = len(items)

            # ------------------------------------------------------ (4) deleting records
            print("\n[5] deleting a specific record (10 rubric points)")
            target_id = items[0]["id"]
            other_id = items[1]["id"]

            status, _ = request("DELETE", f"/api/history/{target_id}")
            check("deleting an existing record returns 204", status, 204)

            status, body = request("GET", "/api/history")
            after = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            remaining_ids = [x["id"] for x in after]
            check("the deleted record is really gone", target_id in remaining_ids, False)
            check("the other records are unaffected", other_id in remaining_ids, True)
            check("the total is one lower", len(after), count_before - 1)

            status, body = request("DELETE", "/api/history/999999")
            check("deleting a missing record returns 404", status, 404)
            code = body.get("errorCode") if isinstance(body, dict) else None
            check("correct error code", code, "RECORD_NOT_FOUND")

            # ------------------------------------------------------ extra endpoints
            print("\n[6] extra endpoints")
            status, body = request("GET", "/api/stats")
            check("GET /api/stats returns 200", status, 200)

            status, _ = request("DELETE", "/api/history")
            check("DELETE /api/history clear returns 200", status, 200)
            status, body = request("GET", "/api/history")
            check("no records left after clearing", body.get("data", {}).get("items", []), [])

            # ------------------------------------------------------ persistence check
            print("\n[7] persistence check: history survives a service restart")
            request("POST", "/api/calculate", {"expression": "7*6"})

            proc.terminate()
            proc.wait(timeout=10)
            print("  service stopped")

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
                print("  restart failed")
                return 2
            print("  service restarted (same database file)")

            status, body = request("GET", "/api/history")
            items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
            expressions = [x["expression"] for x in items]
            check("history is still there after the restart", expressions, ["7*6"])
            stored = items[0]["result"] if items else None
            check("the stored result is still correct after the restart", stored, "42")

            # ------------------------------------------------------ expression preserved
            print("\n[8] the expression is kept as sent (backend parses ASCII)")
            status, body = request("POST", "/api/calculate", {"expression": "12+8"})
            check(
                "the returned expression matches the request",
                body.get("data", {}).get("expression") if isinstance(body, dict) else None,
                "12+8",
            )

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()

    # ---------------------------------------------------------------- summary
    return _report()


def _report() -> int:
    """Print the summary and return the exit code."""
    total = passed + len(failures)
    print("\n" + "=" * 62)
    if not failures:
        print(f"black-box acceptance passed: {passed}/{total}")
        print("=" * 62)
        return 0

    print(f"black-box acceptance failed {len(failures)} of {total}:")
    for item in failures:
        print(f"  ✗ {item}")
    print("=" * 62)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
