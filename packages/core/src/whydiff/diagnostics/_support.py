from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import JsonValue

from whydiff.models import DiagnosticFinding, FindingStatus, Relation

QueryParameters = Sequence[object] | Mapping[str, object]


def relation_sql(adapter: Any, relation: Relation | str) -> str:
    return str(adapter.render_relation(as_relation(relation)))


def as_relation(relation: Relation | str) -> Relation:
    return Relation(name=relation) if isinstance(relation, str) else relation


def quoted_columns(adapter: Any, columns: Sequence[str]) -> tuple[str, ...]:
    if not columns:
        raise ValueError("at least one column is required")
    if len(set(columns)) != len(columns):
        raise ValueError("columns must be unique")
    return tuple(str(adapter.quote_identifier(column)) for column in columns)


def execute_rows(
    adapter: Any,
    sql: str,
    *,
    parameters: QueryParameters | None = None,
    max_rows: int | None = None,
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    result = adapter.execute(sql, parameters=parameters, max_rows=max_rows)
    columns = tuple(str(column) for column in result.columns)
    rows = tuple(tuple(row) for row in result.rows)
    return columns, rows


def first_row_dict(
    adapter: Any,
    sql: str,
    *,
    parameters: QueryParameters | None = None,
) -> dict[str, Any]:
    columns, rows = execute_rows(adapter, sql, parameters=parameters, max_rows=1)
    if not rows:
        return {}
    return dict(zip(columns, rows[0], strict=True))


def row_dicts(
    adapter: Any,
    sql: str,
    *,
    parameters: QueryParameters | None = None,
    max_rows: int,
) -> list[dict[str, Any]]:
    columns, rows = execute_rows(adapter, sql, parameters=parameters, max_rows=max_rows)
    return [dict(zip(columns, row, strict=True)) for row in rows]


def bound_parameter_metadata(parameters: Mapping[str, object]) -> list[dict[str, str]]:
    """Describe bindings without retaining their potentially sensitive values."""
    return [
        {"name": str(name), "type": type(value).__name__}
        for name, value in sorted(parameters.items())
    ]


def json_safe(value: Any) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_safe(item) for item in value]
    return str(value)


def json_object(value: dict[str, Any]) -> dict[str, JsonValue]:
    return {str(key): json_safe(item) for key, item in value.items()}


def finding(
    *,
    code: str,
    status: FindingStatus,
    message: str,
    sql: str,
    evidence: dict[str, Any],
    classification: str,
    sample_sql: str | Iterable[str] | None = None,
    execution_metadata: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DiagnosticFinding:
    finding_metadata: dict[str, JsonValue] = {"classification": classification}
    finding_metadata.update(json_object(metadata or {}))
    if sample_sql is not None:
        finding_metadata["sample_sql"] = json_safe(sample_sql)
    return DiagnosticFinding(
        code=code,
        status=status,
        message=message,
        generated_sql=sql,
        evidence=json_object(evidence),
        execution_metadata=json_object(execution_metadata or {}),
        metadata=finding_metadata,
    )


def value_from(row: dict[str, Any], name: str, position: int = 0) -> Any:
    if name in row:
        return row[name]
    return tuple(row.values())[position]
