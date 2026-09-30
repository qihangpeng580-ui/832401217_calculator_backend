"""src package -- root of the back-end source code.

------------------------------------------------------------------
Layer responsibilities at a glance
------------------------------------------------------------------

    calculator/   pure computation; no database, no HTTP; testable on its own
        tokenizer.py    string -> tokens
        parser.py       tokens -> syntax tree
        evaluator.py    syntax tree -> result

    service/      orchestration: combines "compute" and "store" as the business needs
        calculator_service.py   parse + evaluate + format
        history_service.py      write to the database after calculating; query and delete history

    model/        persistence
        sqlite_store.py         SQLite inserts, queries and deletes

    controller/   external interface
        http_controller.py      HTTP routing, request parsing, response output

    common/       shared across layers
        errors.py               central error definitions (error code <-> HTTP status code)

------------------------------------------------------------------
Dependency direction (downward only)
------------------------------------------------------------------

    controller  ->  service  ->  calculator
                       |
                    model

A reverse dependency would break testability: if calculator imported model,
it could only be tested with a database present, and the fastest 100+ of the
157 unit tests would no longer run.

------------------------------------------------------------------
How to start
------------------------------------------------------------------

    Start the service with run.py in the project root:

        py -3.12 run.py

    This file only documents the package and contains no executable code,
    so there is exactly one entry point and no way for two start-up paths to
    behave differently.
"""
