# Code Standard Notes (Back-End)

> **Where the standard comes from**:
>
> - **PEP 8 — Style Guide for Python Code** — https://peps.python.org/pep-0008/
> - **PEP 257 — Docstring Conventions** — https://peps.python.org/pep-0257/
> - **Google Python Style Guide** — https://google.github.io/styleguide/pyguide.html
>   Type annotations and the way docstrings are organized follow this one
>
> This document explains which of their rules this repository actually adopts, where it makes trade-offs, and why.
> It lists only what we genuinely comply with, rather than copying a checklist we would never use.

---

## 1. Files and Encoding

| Item | Rule | Basis |
|---|---|---|
| Encoding | Always UTF-8 (no BOM) | Not mandated by PEP 8, but UTF-8 is the default source encoding in Python 3 |
| Indentation | **4 spaces**, tabs forbidden | Required by PEP 8 |
| Line width | 100 characters or fewer (recommended) | PEP 8 specifies 79; this repository relaxes it to 100 (see §7) |
| File naming | lowercase with underscores, e.g. `http_controller.py` | PEP 8 |
| Package / module layout | `src/<layer>/<module>.py` | Defined by this project to keep the layering clear |

## 2. Naming (PEP 8, Section 3)

| Kind | Rule | Examples in this repository |
|---|---|---|
| Module names | `lower_snake_case` | `sqlite_store`, `calculator_service` |
| Class names | `CapWords` | `CalculatorService`, `SqliteStore`, `Token` |
| Functions / methods | `lower_snake_case` | `calculate_and_save`, `list_recent` |
| Constants (module level) | `UPPER_SNAKE_CASE` | `MAX_EXPRESSION_LENGTH`, `DEFAULT_HISTORY_LIMIT` |
| Private members | Leading single underscore | `self._store`, `_parse_expression` |
| Enum members | `UPPER_SNAKE_CASE` | `TokenType.NUMBER` |
| Boolean variables | Prefixed with `is` / `has` / `can` | `is_finite`, `has_alpha` |

**Division of labor between API field names and database column names** (a convention specific to this repository):

| Where | Style | Example |
|---|---|---|
| Database column names | `snake_case` (SQL convention) | `created_at` |
| JSON fields sent to the front-end | `camelCase` (JS convention) | `createdAt` |

The conversion happens in `_to_dict()` in `sqlite_store.py`, and **nowhere else**.

## 3. Type Annotations (following the Google Python Style Guide)

**Every function in this repository carries type annotations**, including return values:

```python
def calculate(self, expression: str) -> CalculationOutcome:
    ...
```

Optional values use `X | None` (the PEP 604 syntax, which requires Python 3.10+):

```python
def get(self, record_id: int) -> dict | None:
    ...
```

**Why we insist on annotations**:
1. The editor catches type errors before you ever run the code;
2. Annotations are **documentation** in their own right — seeing `-> dict | None` tells you "this may return
   nothing", so the caller remembers to handle the empty case and that whole class of bugs is avoided up front;
3. This project uses `from __future__ import annotations`, so annotations do not raise errors on older Python versions either.

## 4. Docstrings (PEP 257 + Google style)

**Every module and every public function has a docstring.** The rules:

1. The first line is a **one-sentence summary** ending with a period;
2. A blank line follows, then the detailed description (if one sentence is not enough);
3. Arguments, return values, and exceptions go in `Args:` / `Returns:` / `Raises:` sections (Google style).

```python
def insert(self, expression: str, result: str) -> dict:
    """Insert one calculation record.

    Args:
        expression: The expression entered by the user (stored verbatim)
        result: The normalized result string

    Returns:
        The complete newly inserted record (including the auto-increment id and creation time)
    """
```

**A convention specific to this repository: docstrings should explain *why*, not just *what*.**

Take this one from `tokenizer.py`, for example:

```python
def _parse_number(raw: str, pos: int) -> Decimal:
    """Convert a run of numeric text into a Decimal.

    Why Decimal instead of float:
        float is a binary floating-point type, so 0.1 + 0.2 yields 0.30000000000000004.
        A calculator has to answer 0.3. Decimal is decimal floating point and can represent 0.1 and 0.2 exactly.
    """
```

Explanations like this take up a fair amount of space, but they are **part of what this assignment is graded on** — the
assignment prompt explicitly asks for "an explanation of the important implementation logic", not just a pile of code that runs.

## 5. Layering and Dependency Direction

```
controller  →  service  →  calculator (pure computation, no side effects)
                    ↓
                 model (database)
```

**Three hard rules:**

1. **Dependencies point one way only**: the `calculator` layer may not import `service` or `model`.
   The pure computation layer has to be testable independently of the database and HTTP (`tests/test_calculator.py` never creates a database).
2. **Errors are defined in exactly one place**: all business exceptions live in `common/errors.py`.
   Business code never writes `return 400`; it raises the matching exception, and the outermost layer translates it into a status code.
3. **Database details do not leak**: SQL appears only in `sqlite_store.py`.
   By the time the service layer sees the data it is already a Python dict, with no idea that SQLite is underneath.

## 6. Security Rules (hard requirements for this project)

| Rule | Notes |
|---|---|
| **`eval` / `exec` / `compile` are forbidden** | The assignment explicitly forbids executing user input as code. `tests/test_calculator.py` contains a **static check test** that scans all source files and fails if any of these calls appear |
| **The back-end must validate input on its own** | The front-end does block invalid input, but the API can be called directly with `curl`, so the front-end cannot be trusted |
| **Request body size limit** | `MAX_BODY_BYTES = 64KB`, to block oversized requests |
| **Expression length limit** | `MAX_EXPRESSION_LENGTH = 200` |
| **Exceptions do not leak details** | A 500 response returns only a generic message; the stack trace goes to the server-side log |

## 7. Trade-offs in This Repository

| Rule | Trade-off | Reason |
|---|---|---|
| PEP 8's 79-character line width | Relaxed to 100 | A comment line often needs a few more characters than 79 to explain a decision without wrapping awkwardly |
| Google style's 100% test coverage requirement | Not enforced | But the core modules (tokenizer / parser / evaluator / store) all have tests, 157 in total |
| Adopting formatters such as `black` / `flake8` | Not adopted | `pip install` is unavailable on this machine (restricted network); a consistent hand-written style takes its place |
| Adopting the `mypy` type checker | Not adopted | Same reason; but the type annotations are complete, so it can be plugged in at any time |
| Adopting a web framework (Flask / FastAPI) | Not adopted | See README §2: an all-standard-library stack buys "the TA can just run it" |
| Using `dataclass` instead of plain classes | Adopted | Syntax tree nodes and result objects are pure data; `@dataclass(frozen=True)` generates `__eq__` and `__repr__` automatically, so tests can compare objects directly |

## 8. Commit Messages

A simplified form of Conventional Commits:

```
<type>: <short description>
```

| type | Meaning |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `test` | Test-only change |
| `docs` | Documentation-only change |
| `refactor` | Refactoring with no behavior change |
| `chore` | Chores (config, ignore files, and so on) |

## 9. Self-Check List (go through every item before committing)

- [ ] `py -3.12 -m unittest discover -s tests` all pass
- [ ] `py -3.12 tools/blackbox.py` all pass
- [ ] Searching the whole repository for `eval(` / `exec(` / `compile(` returns no hits (excluding `re.compile`)
- [ ] Every module and every public function has a docstring
- [ ] Every function has type annotations
- [ ] No leftover `print()` debugging (other than the service startup message)
- [ ] All files are UTF-8 with 4-space indentation
- [ ] The database file `data/*.db` is not committed (gitignored)
