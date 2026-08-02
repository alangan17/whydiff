"""Conservative SQL validation for WhyDiff's read-only execution boundary."""

from __future__ import annotations

import re

from sqlglot import exp, parse
from sqlglot.errors import ParseError

_EXTERNAL_OR_DYNAMIC_FUNCTIONS = frozenset(
    {
        "csv_scan",
        "delta_scan",
        "glob",
        "iceberg_scan",
        "mysql_scan",
        "parquet_scan",
        "postgres_scan",
        "query",
        "query_table",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_ndjson",
        "read_parquet",
        "sqlite_scan",
    }
)
_UNSAFE_LEADING_KEYWORDS = frozenset(
    {
        "ALTER",
        "ATTACH",
        "BEGIN",
        "CALL",
        "COMMIT",
        "COPY",
        "CREATE",
        "DELETE",
        "DETACH",
        "DROP",
        "EXPORT",
        "IMPORT",
        "INSERT",
        "INSTALL",
        "LOAD",
        "MERGE",
        "PRAGMA",
        "RESET",
        "ROLLBACK",
        "SET",
        "TRUNCATE",
        "UPDATE",
        "USE",
        "VACUUM",
    }
)
_UNSAFE_NODE_KEYS = frozenset(keyword.casefold() for keyword in _UNSAFE_LEADING_KEYWORDS)


class SQLSafetyError(ValueError):
    """Base error for SQL rejected before reaching a database."""


class MultipleStatementsError(SQLSafetyError):
    """Raised when input contains more than one SQL statement."""


class UnsafeStatementError(SQLSafetyError):
    """Raised when SQL could mutate state, perform I/O, or execute dynamic SQL."""


def validate_read_only_sql(sql: str) -> exp.Query:
    """Parse and return one query expression, rejecting everything except read-only SQL.

    The allow-list is intentionally narrow: a top-level query (`SELECT`, `WITH`, or a
    set operation) with no external-I/O or dynamic-SQL table functions. Parsing occurs
    in DuckDB's dialect, while DuckDB-specific commands are rejected by the allow-list.
    """
    if not sql.strip():
        raise SQLSafetyError("SQL must not be empty")

    try:
        statements = [statement for statement in parse(sql, read="duckdb") if statement is not None]
    except ParseError as error:
        first_word = re.match(r"\s*([A-Za-z]+)", sql)
        if first_word and first_word.group(1).upper() in _UNSAFE_LEADING_KEYWORDS:
            raise UnsafeStatementError(
                f"{first_word.group(1).upper()} statements are not allowed"
            ) from error
        raise SQLSafetyError("SQL could not be parsed safely") from error

    if not statements:
        raise SQLSafetyError("SQL must contain one statement")
    if len(statements) != 1:
        raise MultipleStatementsError("exactly one SQL statement is allowed")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise UnsafeStatementError(
            f"{type(statement).__name__} statements are not allowed; expected a read-only query"
        )

    for node in statement.walk():
        if node.key in _UNSAFE_NODE_KEYS:
            raise UnsafeStatementError(f"{type(node).__name__} clauses are not allowed")
        if isinstance(node, exp.Func):
            function_names = {node.name.casefold(), node.sql_name().casefold()}
            blocked_names = function_names & _EXTERNAL_OR_DYNAMIC_FUNCTIONS
            if blocked_names:
                raise UnsafeStatementError(f"function {blocked_names.pop()!r} is not allowed")
        if (
            isinstance(node, exp.Table)
            and isinstance(node.this, exp.Func)
            and not isinstance(node.this, exp.GenerateSeries)
        ):
            raise UnsafeStatementError("table functions are not allowed")
        if isinstance(node, exp.Table) and isinstance(node.this, exp.Literal):
            raise UnsafeStatementError("relations backed by external path literals are not allowed")

    return statement


__all__ = [
    "MultipleStatementsError",
    "SQLSafetyError",
    "UnsafeStatementError",
    "validate_read_only_sql",
]
