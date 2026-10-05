# Front-End / Back-End Separated Calculator · Back-End (Student ID 832401217)

The **back-end half** of the "front-end / back-end separated calculator system" assignment for the Software Engineering course.
It is responsible for expression parsing, evaluation, and exception handling, as well as persisting calculation history in a database.

> Front-end repository: [832401217_calculator_frontend](https://github.com/qihangpeng580-ui/832401217_calculator_frontend)

---

## 1. Project Overview

This is an HTTP service that exposes calculation and history APIs to the front-end. It carries **all of the calculation responsibility** required by the assignment:

| Handled by this project | Not part of this project |
|---|---|
| Expression tokenization and parsing (no `eval`) | Interface presentation |
| The four basic operations, operator precedence, parentheses, unary plus / minus | Button interaction |
| Exact decimal arithmetic (using `Decimal`, not floating point) | Front-end input validation |
| Invalid expression handling, division-by-zero handling | — |
| Writing calculation history to the database | — |
| Querying and deleting history | — |

**Core design principle**: the API can be called directly (with `curl`, for instance),
so **front-end validation cannot be trusted**. Any illegal input the front-end blocks, the back-end must block again on its own.

## 2. Tech Stack

| Item | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ (developed on 3.12) | Uses `X \| None` type annotations, hence the 3.10+ requirement |
| HTTP server | `http.server` (standard library) | Hand-written routing, no framework |
| Database | SQLite (`sqlite3`, standard library) | Single-file database |
| Numeric type | `decimal.Decimal` (standard library) | Guarantees 0.1+0.2 = 0.3 |
| Testing | `unittest` (standard library) | 157 unit tests + 39 black-box acceptance tests |
| **Third-party dependencies** | **None** | `requirements.txt` is empty, so no `pip install` is needed |

**Why everything comes from the standard library**: once the TA has the code, it runs as-is on any machine with Python installed —
no environment to set up, no database service to install. This is a portability trade-off:
we give up the convenience of a framework in exchange for "it just runs".

## 3. Directory Structure

```
832401217_calculator_backend/
├── run.py                          Service entry point (CLI arguments, starts the HTTP server)
├── init_db.py                      Standalone database-creation script (for when the service is not running)
├── requirements.txt                Empty (no third-party dependencies)
├── README.md                       This file
├── codestyle.md                    Code standard notes
├── src/
│   ├── main.py                     Module overview and wiring example
│   ├── calculator/                 Expression processing (the core of this project)
│   │   ├── tokenizer.py            Tokenization: string → token sequence
│   │   ├── parser.py               Parsing: token sequence → syntax tree (recursive descent)
│   │   └── evaluator.py            Evaluation: syntax tree → result (post-order traversal)
│   ├── service/
│   │   ├── calculator_service.py   Orchestrates "parse → evaluate → format"
│   │   └── history_service.py      Orchestrates "calculate + write to the DB", history queries and deletion
│   ├── model/
│   │   └── sqlite_store.py         SQLite reads and writes
│   ├── controller/
│   │   └── http_controller.py      HTTP API layer (routing, request parsing, response output, CORS)
│   └── common/
│       └── errors.py               Central error definitions (error code ↔ HTTP status code)
├── tests/
│   ├── test_tokenizer.py           26 tests
│   ├── test_parser.py              38 tests
│   ├── test_calculator.py          66 tests (including security tests)
│   └── test_store.py               27 tests
├── tools/
│   ├── blackbox.py                 Black-box acceptance: drives the full flow with real HTTP requests
│   └── push_via_api.py             Push via the GitHub API — a fallback when local git push does not work
└── data/                           calculator.db is created here at runtime (gitignored)
```

How the layers call one another (one-way; reverse dependencies are not allowed):

```
http_controller  →  history_service  →  calculator_service  →  parser / evaluator
                          ↓
                     sqlite_store
```

## 4. How to Run

```powershell
# Enter the back-end directory
cd "832401217_calculator_backend"

# Start the service (defaults to 127.0.0.1:8000; the database is created automatically on first run)
py -3.12 run.py

# Use a different port
py -3.12 run.py --port 8080

# Allow outside access (for a tunnel or a server deployment)
py -3.12 run.py --host 0.0.0.0
```

Once it is running, opening <http://127.0.0.1:8000/api/health> in a browser should show:

```json
{"success": true, "data": {"status": "ok", "service": "calculator-backend", ...}}
```

**Runtime requirements**

| Item | Requirement |
|---|---|
| Python | **3.10 or later** (uses `X \| None` annotations) |
| Third-party packages | **None** |
| Database service | **Not needed** (SQLite is a file database) |
| Operating system | Any (Windows / Linux / macOS) |

## 5. Configuration

### 5.1 Command-Line Arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Listen address. Change it to `0.0.0.0` to accept outside connections |
| `--port` | `8000` | Listen port |
| `--db` | `data/calculator.db` | Path to the SQLite database file |

### 5.2 Tunable Constants in the Code

| Location | Constant | Default | Purpose |
|---|---|---|---|
| `tokenizer.py` | `MAX_EXPRESSION_LENGTH` | 200 | Maximum expression length |
| `evaluator.py` | `PRECISION` | 28 | Decimal arithmetic precision |
| `evaluator.py` | `MAX_RESULT_SCALE` | 12 | Maximum number of decimal places kept in the result |
| `http_controller.py` | `DEFAULT_HISTORY_LIMIT` | 50 | Default number of history records returned |
| `http_controller.py` | `MAX_HISTORY_LIMIT` | 200 | Maximum number of history records returned per request |
| `http_controller.py` | `MAX_BODY_BYTES` | 65536 | Maximum request body size |

### 5.3 Cross-Origin (CORS)

It is currently configured as `Access-Control-Allow-Origin: *` (any origin is allowed).
That way the front-end can call the API whether it is deployed on GitHub Pages, opened locally through `file://`, or served on a LAN.

**This is a trade-off for the assignment setting**: the address is not known in advance, so it is left open.
A production deployment should switch to a whitelist that allows only the front-end's own domain.

## 6. Database Initialization

**No manual initialization is needed** — the service creates the table automatically on startup (`CREATE TABLE IF NOT EXISTS`).

If you want to create the database on its own (to have the file ready before deploying, for example):

```powershell
py -3.12 init_db.py
```

### Table Schema

```sql
CREATE TABLE IF NOT EXISTS calculation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expression  TEXT    NOT NULL,   -- expression as entered by the user, stored verbatim
    result      TEXT    NOT NULL,   -- result, stored as a string to preserve decimal precision
    created_at  TEXT    NOT NULL    -- ISO-8601 timestamp
);

CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON calculation_history (created_at DESC);
```

**Two design decisions:**

| Decision | Rationale |
|---|---|
| `result` is stored as `TEXT` rather than `REAL` | `REAL` is binary floating point: store `0.3` and read it back, and you may get `0.29999999999999998`. Storing a string keeps the decimal value exact |
| An index on `created_at` | "Fetch the most recent N records in reverse chronological order" is the most frequent query (the front-end issues it the moment it loads) |

## 7. How the Front-End and Back-End Connect

The front-end calls this service over HTTP. API overview:

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/calculate` | Calculate and save to history |
| `GET` | `/api/history` | Query history (supports `keyword`, `limit`) |
| `DELETE` | `/api/history/{id}` | Delete a specific record |
| `DELETE` | `/api/history` | Clear all history (extension) |
| `GET` | `/api/stats` | Statistics (extension) |
| `GET` | `/api/health` | Health check |

### Request / Response Examples

**Calculate**

```http
POST /api/calculate
Content-Type: application/json

{"expression": "1+2*3"}
```

```json
{
  "success": true,
  "data": {"expression": "1+2*3", "result": "7", "resultNumber": 7.0}
}
```

**Pagination and Statistics**

```text
GET /api/history?limit=5
```

```json
{"success": true, "data": {"items": [{"id": 2, "expression": "7*6", "result": "42", "createdAt": "2026-09-29T15:20:11"}], "total": 2, "limit": 5, "keyword": ""}}
```

**Unified Error Format**

```json
{
  "success": false,
  "errorCode": "DIVISION_BY_ZERO",
  "message": "Division by zero is not allowed"
}
```

| errorCode | HTTP | Triggered by |
|---|---|---|
| `INVALID_EXPRESSION` | 400 | Syntax errors, illegal characters, mismatched parentheses, multiple decimal points |
| `DIVISION_BY_ZERO` | 422 | Divisor is 0 (including expressions that evaluate to 0) |
| `EXPRESSION_TOO_LONG` | 413 | Exceeds `MAX_EXPRESSION_LENGTH` |
| `RECORD_NOT_FOUND` | 404 | The record to delete does not exist |
| `BAD_REQUEST` | 400 | Request body is not valid JSON, or the `expression` field is missing |
| `INTERNAL_ERROR` | 500 | Unexpected server-side error |

> The error codes in this table **map one-to-one to `SERVER_ERROR_TEXT` in the front-end's `ui.js`**,
> which is how the front-end turns an error code into a user-facing message.

### A Detail That Makes Verification Easy

Every response carries a custom header:

```
X-Calculated-By: backend
```

Open `F12` in the browser → Network → click any `/api/calculate` request,
and you will find it under Response Headers. It is the evidence for the question "who actually computed this result?"

## 8. Testing

### 8.1 Unit Tests (157 tests, about 1 second)

```powershell
py -3.12 -m unittest discover -s tests -v
```

| File | Tests | Coverage |
|---|---|---|
| `test_tokenizer.py` | 26 | Splitting numbers / operators / parentheses, whitespace handling, illegal characters, length limit, code-injection rejection |
| `test_parser.py` | 38 | Precedence, left associativity, parentheses, unary plus / minus, various invalid expressions |
| `test_calculator.py` | 66 | The assignment's sample expressions, decimal precision, division by zero, security, result formatting |
| `test_store.py` | 27 | Table creation, insert, query, search, deleting a single record, clearing all, statistics |

### 8.2 Black-Box Acceptance Tests (39 tests, about 10 seconds)

```powershell
py -3.12 tools/blackbox.py
```

This script **starts a real service** and drives the four things the assignment asks for with **real HTTP requests**:

1. Basic arithmetic (`12+8 = 20`, and so on)
2. Compound expressions (precedence, parentheses, unary plus / minus, decimals, invalid expressions, division by zero)
3. History persistence — including **history still being there after the service restarts**
4. Deleting a specific record — and confirming that "only the specified record was deleted and the rest are untouched"

**Why it is needed on top of the unit tests**: unit tests call functions directly, bypassing the HTTP layer.
But what the assignment delivers is a **service reachable over the network**, so at least one test has to genuinely go over the network.
The front-end project learned this the hard way: every function test was green, yet opening the page through `file://` gave no interactivity at all.

## 9. Deployment

**Deployed on a cloud server and reachable from the public internet.**

**Project site (the link for the instructor / TA)**:

# <http://118.31.246.176:8000/>

It opens straight into the calculator, and `=` computes immediately — because this service **also hosts the front-end page**,
so the page and the API share a single address (same-origin) and there is no cross-origin issue.

| Item | Value |
|---|---|
| Server | Alibaba Cloud ECS, China (Hangzhou) East 1, 2 cores / 2 GB, Ubuntu 24.04 |
| Service port | `8000`; this is the only port opened in the cloud console's security group |
| Health check | <http://118.31.246.176:8000/api/health> |
| Startup | systemd service `calculator-backend`, **starts on boot + auto-restarts on crash** |
| Database | `/var/lib/calculator-backend/calculator.db`, a single SQLite file |
| Service user | `calcapp`, a dedicated low-privilege system user; **does not run as root** |

One-command deployment:

```bash
cd 832401217_calculator_backend
./deploy.sh
```

The script does the following in order: check the Python version (3.10+ required) → copy the code to `/opt/calculator-backend`
→ create the dedicated user → initialize the database → fetch the front-end page and make it same-origin → register the systemd service
→ open the local firewall → start the service and run a health check.

Common operations commands:

```bash
systemctl status  calculator-backend     # Check status
systemctl restart calculator-backend     # Restart
journalctl -u calculator-backend -f      # Follow the logs live
```

> **Do not forget the security group after deploying**: the script can only open the server's **local** firewall (ufw/firewalld);
> the **security group** in the cloud console is a separate, outer layer. The symptom of missing it is
> "the script succeeded all the way through, but the browser cannot open the page".

**Running locally** (for development): <http://127.0.0.1:8000/api/health>

## 10. Known Trade-offs and Limitations

| Item | Current state | Notes |
|---|---|---|
| CORS | Any origin allowed | The address is not fixed in the assignment setting; production should use a whitelist |
| Authentication | None | Not required by the assignment; anyone can call the API |
| Concurrency | Multithreaded, with a new database connection per operation | Enough for the assignment's scale; high concurrency would call for a connection pool |
| History size | No limit | It keeps growing over a long run; production should add a cleanup policy |
| Scientific functions | Not implemented | An extension feature, optional |
