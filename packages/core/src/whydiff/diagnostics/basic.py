from __future__ import annotations

from typing import Any

from whydiff.models import DiagnosticFinding, FindingStatus, Relation

from ._support import (
    as_relation,
    bound_parameter_metadata,
    execute_rows,
    finding,
    first_row_dict,
    relation_sql,
    value_from,
)


def _schema_query(
    relation: Relation | str,
    *,
    parameter_prefix: str = "relation",
) -> tuple[str, dict[str, object]]:
    relation_model = as_relation(relation)
    parameters: dict[str, object] = {
        f"{parameter_prefix}_table_name": relation_model.name,
    }
    predicates = [f"table_name = ${parameter_prefix}_table_name"]
    schema_parameter = f"{parameter_prefix}_table_schema"
    predicates.append(
        f"table_schema = ${schema_parameter}"
        if relation_model.schema is not None
        else "table_schema = current_schema()"
    )
    if relation_model.schema is not None:
        parameters[schema_parameter] = relation_model.schema
    if relation_model.catalog is not None:
        catalog_parameter = f"{parameter_prefix}_table_catalog"
        predicates.append(f"table_catalog = ${catalog_parameter}")
        parameters[catalog_parameter] = relation_model.catalog
    sql = (
        "SELECT column_name, data_type FROM information_schema.columns WHERE "
        f"{' AND '.join(predicates)} ORDER BY ordinal_position"
    )
    return sql, parameters


def _describe(
    adapter: Any,
    relation: Relation | str,
    *,
    parameter_prefix: str = "relation",
) -> tuple[str, dict[str, str], dict[str, object]]:
    sql, parameters = _schema_query(relation, parameter_prefix=parameter_prefix)
    columns, rows = execute_rows(adapter, sql, parameters=parameters)
    name_index = columns.index("column_name") if "column_name" in columns else 0
    type_index = columns.index("column_type") if "column_type" in columns else 1
    schema = {str(row[name_index]): str(row[type_index]) for row in rows}
    if not schema:
        raise LookupError("relation does not exist or has no inspectable columns")
    return sql, schema, parameters


def inspect_relation(
    adapter: Any,
    relation: Relation | str,
    requested_columns: tuple[str, ...] | list[str] = (),
) -> DiagnosticFinding:
    rendered = relation_sql(adapter, relation)
    sql, parameters = _schema_query(relation)
    try:
        sql, schema, parameters = _describe(adapter, relation)
    except Exception as exc:
        return finding(
            code="missing_relation",
            status=FindingStatus.FAILURE,
            message=f"Relation {rendered} could not be inspected.",
            sql=sql,
            evidence={"relation": rendered, "error_type": type(exc).__name__},
            classification="confirmed",
            execution_metadata={
                "queries_executed": 1,
                "bound_parameters": bound_parameter_metadata(parameters),
            },
        )

    missing = sorted(set(requested_columns).difference(schema))
    if missing:
        return finding(
            code="missing_columns",
            status=FindingStatus.FAILURE,
            message=f"Relation {rendered} is missing {len(missing)} requested column(s).",
            sql=sql,
            evidence={"relation": rendered, "missing_columns": missing, "columns": schema},
            classification="confirmed",
            execution_metadata={
                "queries_executed": 1,
                "bound_parameters": bound_parameter_metadata(parameters),
            },
        )
    return finding(
        code="relation_inspected",
        status=FindingStatus.INFO,
        message=f"Relation {rendered} exists and contains all requested columns.",
        sql=sql,
        evidence={"relation": rendered, "columns": schema},
        classification="confirmed",
        execution_metadata={
            "queries_executed": 1,
            "bound_parameters": bound_parameter_metadata(parameters),
        },
    )


def _potentially_lossy(left_type: str, right_type: str) -> bool:
    left = left_type.upper()
    right = right_type.upper()
    if left == right:
        return False
    text_tokens = ("CHAR", "VARCHAR", "TEXT")
    if any(token in left for token in text_tokens) != any(token in right for token in text_tokens):
        return True
    numeric_rank = {
        "TINYINT": 1,
        "SMALLINT": 2,
        "INTEGER": 3,
        "BIGINT": 4,
        "HUGEINT": 5,
        "REAL": 6,
        "FLOAT": 6,
        "DOUBLE": 7,
    }
    if left in numeric_rank and right in numeric_rank:
        return numeric_rank[left] != numeric_rank[right]
    if left.startswith("DECIMAL") or right.startswith("DECIMAL"):
        return left != right
    return True


def compare_schema(
    adapter: Any,
    left: Relation | str,
    right: Relation | str,
) -> DiagnosticFinding:
    left_sql, left_schema, left_parameters = _describe(adapter, left, parameter_prefix="left")
    right_sql, right_schema, right_parameters = _describe(adapter, right, parameter_prefix="right")
    left_only = sorted(set(left_schema).difference(right_schema))
    right_only = sorted(set(right_schema).difference(left_schema))
    mismatches = [
        {
            "column": name,
            "left_type": left_schema[name],
            "right_type": right_schema[name],
            "potentially_lossy": _potentially_lossy(left_schema[name], right_schema[name]),
        }
        for name in sorted(set(left_schema).intersection(right_schema))
        if left_schema[name].upper() != right_schema[name].upper()
    ]
    evidence = {
        "left_only": left_only,
        "right_only": right_only,
        "type_mismatches": mismatches,
    }
    differs = bool(left_only or right_only or mismatches)
    generated_sql = (
        f"SELECT 'left' AS relation_side, * FROM ({left_sql}) AS left_schema\n"
        "UNION ALL\n"
        f"SELECT 'right' AS relation_side, * FROM ({right_sql}) AS right_schema"
    )
    return finding(
        code="schema_mismatch" if differs else "schema_match",
        status=FindingStatus.FAILURE if differs else FindingStatus.INFO,
        message="Relation schemas differ." if differs else "Relation schemas match.",
        sql=generated_sql,
        evidence=evidence,
        classification="confirmed",
        execution_metadata={
            "queries_executed": 2,
            "bound_parameters": bound_parameter_metadata(left_parameters | right_parameters),
        },
    )


def compare_row_counts(
    adapter: Any,
    left: Relation | str,
    right: Relation | str,
) -> DiagnosticFinding:
    left_sql = relation_sql(adapter, left)
    right_sql = relation_sql(adapter, right)
    sql = (
        "SELECT "
        f"(SELECT COUNT(*) FROM {left_sql}) AS left_count, "
        f"(SELECT COUNT(*) FROM {right_sql}) AS right_count"
    )
    row = first_row_dict(adapter, sql)
    left_count = int(value_from(row, "left_count", 0))
    right_count = int(value_from(row, "right_count", 1))
    difference = abs(left_count - right_count)
    denominator = max(left_count, right_count)
    percentage = 0.0 if denominator == 0 else round(difference * 100.0 / denominator, 6)
    differs = difference > 0
    return finding(
        code="row_count_mismatch" if differs else "row_count_match",
        status=FindingStatus.WARNING if differs else FindingStatus.INFO,
        message="Row counts differ; this is a signal, not a confirmed cause."
        if differs
        else "Row counts match.",
        sql=sql,
        evidence={
            "left_count": left_count,
            "right_count": right_count,
            "absolute_difference": difference,
            "percentage_difference": percentage,
        },
        classification="hypothesis" if differs else "confirmed",
        execution_metadata={"queries_executed": 1},
    )
