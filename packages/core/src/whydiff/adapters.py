"""Database adapter contracts and the secure DuckDB implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from threading import Event, Timer
from time import perf_counter
from types import TracebackType
from typing import Any, Literal, Self

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from whydiff.models import Relation
from whydiff.sql_safety import (
    MultipleStatementsError,
    SQLSafetyError,
    UnsafeStatementError,
    validate_read_only_sql,
)

QueryParameters = Sequence[object] | Mapping[str, object]


class AdapterError(RuntimeError):
    """Base error for failures at the adapter boundary."""


class AdapterClosedError(AdapterError):
    """Raised when execution is attempted after an adapter has closed."""


class QueryTimeoutError(AdapterError):
    """Raised when a query exceeds its configured execution deadline."""


class ResultLimitError(AdapterError):
    """Raised when a requested result limit is invalid or cannot be enforced."""


class QueryAudit(BaseModel):
    """Sanitized, JSON-safe facts about an adapter execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["duckdb"] = "duckdb"
    statement_type: str
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows_returned: int = Field(ge=0)
    truncated: bool
    elapsed_ms: float = Field(ge=0)


class QueryResult(BaseModel):
    """Materialized tabular result returned through the adapter contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool
    audit: QueryAudit


class BaseAdapter(ABC):
    """Minimal lifecycle and query contract shared by database adapters."""

    @staticmethod
    def quote_identifier(identifier: str) -> str:
        """Quote one SQL identifier, escaping embedded quote characters."""
        if not identifier:
            raise ValueError("identifier must not be empty")
        return f'"{identifier.replace(chr(34), chr(34) * 2)}"'

    def render_relation(self, relation: Relation) -> str:
        """Render a relation by separately quoting every supplied component."""
        components = [relation.catalog, relation.schema, relation.name]
        return ".".join(self.quote_identifier(part) for part in components if part is not None)

    @abstractmethod
    def execute(
        self,
        sql: str,
        *,
        parameters: QueryParameters | None = None,
        timeout_seconds: float | None = None,
        max_rows: int | None = None,
    ) -> QueryResult:
        """Validate and execute one read-only query."""

    @abstractmethod
    def close(self) -> None:
        """Release resources held by the adapter; repeated calls are safe."""

    def __enter__(self) -> Self:
        """Return this adapter for scoped lifecycle management."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close this adapter when leaving its context."""
        self.close()


class DuckDBAdapter(BaseAdapter):
    """DuckDB adapter that admits only validated read-only query statements."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        read_only: bool | None = None,
        default_timeout_seconds: float | None = None,
        default_max_rows: int = 10_000,
    ) -> None:
        if default_timeout_seconds is not None and default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be greater than zero")
        if default_max_rows <= 0:
            raise ValueError("default_max_rows must be greater than zero")

        database_text = str(database)
        if read_only is None:
            read_only = database_text != ":memory:" and Path(database_text).exists()
        self._connection = duckdb.connect(database_text, read_only=read_only)
        self._default_timeout_seconds = default_timeout_seconds
        self._default_max_rows = default_max_rows
        self._closed = False

    def execute(
        self,
        sql: str,
        *,
        parameters: QueryParameters | None = None,
        timeout_seconds: float | None = None,
        max_rows: int | None = None,
    ) -> QueryResult:
        """Execute safe SQL with optional deadline and bounded materialization."""
        if self._closed:
            raise AdapterClosedError("adapter is closed")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if max_rows is not None and max_rows <= 0:
            raise ValueError("max_rows must be greater than zero")

        parsed = validate_read_only_sql(sql)
        effective_timeout = (
            timeout_seconds if timeout_seconds is not None else self._default_timeout_seconds
        )
        effective_max_rows = max_rows if max_rows is not None else self._default_max_rows
        timed_out = Event()
        timer: Timer | None = None
        started_at = perf_counter()

        if effective_timeout is not None:
            timer = Timer(effective_timeout, self._interrupt, args=(timed_out,))
            timer.daemon = True
            timer.start()

        try:
            if parameters is None:
                cursor = self._connection.execute(sql)
            else:
                cursor = self._connection.execute(sql, parameters)
            columns = tuple(description[0] for description in (cursor.description or ()))
            fetched = cursor.fetchmany(effective_max_rows + 1)
        except duckdb.Error as error:
            if timed_out.is_set():
                raise QueryTimeoutError("query exceeded its execution timeout") from error
            raise AdapterError("DuckDB query execution failed") from error
        finally:
            if timer is not None:
                timer.cancel()

        truncated = len(fetched) > effective_max_rows
        rows = tuple(tuple(row) for row in fetched[:effective_max_rows])
        elapsed_ms = (perf_counter() - started_at) * 1_000
        audit = QueryAudit(
            statement_type=parsed.key.upper(),
            query_hash=sha256(sql.encode("utf-8")).hexdigest(),
            rows_returned=len(rows),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
        )
        return QueryResult(columns=columns, rows=rows, truncated=truncated, audit=audit)

    def _interrupt(self, timed_out: Event) -> None:
        timed_out.set()
        if not self._closed:
            self._connection.interrupt()

    def close(self) -> None:
        """Close the DuckDB connection, safely and idempotently."""
        if not self._closed:
            self._connection.close()
            self._closed = True


__all__ = [
    "AdapterClosedError",
    "AdapterError",
    "BaseAdapter",
    "DuckDBAdapter",
    "MultipleStatementsError",
    "QueryAudit",
    "QueryResult",
    "QueryTimeoutError",
    "ResultLimitError",
    "SQLSafetyError",
    "UnsafeStatementError",
]
