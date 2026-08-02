from __future__ import annotations

from typing import Any

from whydiff.models import DiagnosticFinding, FindingStatus, MeasureConfig, Relation

from ._support import (
    bound_parameter_metadata,
    finding,
    first_row_dict,
    quoted_columns,
    relation_sql,
    row_dicts,
)
from .keys import _limit, _null_safe_join


def analyze_grain(
    adapter: Any,
    relation: Relation | str,
    keys: tuple[str, ...] | list[str],
    *,
    side: str = "relation",
    sample_limit: int = 100,
) -> DiagnosticFinding:
    limit = _limit(sample_limit)
    parameters: dict[str, object] = {"sample_limit": limit}
    quoted = quoted_columns(adapter, keys)
    key_list = ", ".join(quoted)
    rendered = relation_sql(adapter, relation)
    grouped = f"SELECT {key_list}, COUNT(*) AS multiplicity FROM {rendered} GROUP BY {key_list}"
    sql = f"""WITH grouped AS ({grouped})
SELECT
  COALESCE(SUM(multiplicity), 0) AS physical_rows,
  COUNT(*) AS distinct_keys,
  COALESCE(AVG(multiplicity), 0) AS average_multiplicity,
  COALESCE(MAX(multiplicity), 0) AS maximum_multiplicity,
  COUNT(*) FILTER (WHERE multiplicity > 1) AS duplicate_groups,
  COALESCE(SUM(multiplicity - 1) FILTER (WHERE multiplicity > 1), 0) AS excess_rows
FROM grouped"""
    row = first_row_dict(adapter, sql)
    evidence: dict[str, Any] = {
        "side": side,
        "physical_rows": int(row.get("physical_rows", 0)),
        "distinct_keys": int(row.get("distinct_keys", 0)),
        "average_multiplicity": round(float(row.get("average_multiplicity", 0)), 6),
        "maximum_multiplicity": int(row.get("maximum_multiplicity", 0)),
        "duplicate_groups": int(row.get("duplicate_groups", 0)),
        "excess_rows": int(row.get("excess_rows", 0)),
    }
    sample_sql = f"""WITH grouped AS ({grouped})
SELECT * FROM grouped WHERE multiplicity > 1
ORDER BY multiplicity DESC, {key_list} NULLS FIRST LIMIT $sample_limit"""
    evidence["sample"] = row_dicts(adapter, sample_sql, parameters=parameters, max_rows=limit)
    changed = evidence["excess_rows"] > 0
    return finding(
        code="grain_multiplicity" if changed else "grain_exact",
        status=FindingStatus.WARNING if changed else FindingStatus.INFO,
        message=f"{side.capitalize()} relation contains repeated business keys."
        if changed
        else f"{side.capitalize()} relation has one row per business key.",
        sql=sql,
        sample_sql=sample_sql,
        evidence=evidence,
        classification="confirmed",
        execution_metadata={
            "sample_limit": limit,
            "samples_bounded": True,
            "bound_parameters": bound_parameter_metadata(parameters),
        },
    )


def detect_fanout(
    adapter: Any,
    before: Relation | str,
    after: Relation | str,
    keys: tuple[str, ...] | list[str],
    measures: tuple[MeasureConfig, ...] | list[MeasureConfig] = (),
    *,
    sample_limit: int = 100,
) -> tuple[DiagnosticFinding, ...]:
    limit = _limit(sample_limit)
    parameters: dict[str, object] = {"sample_limit": limit}
    before_grain = analyze_grain(adapter, before, keys, side="before", sample_limit=limit)
    after_grain = analyze_grain(adapter, after, keys, side="after", sample_limit=limit)
    quoted = quoted_columns(adapter, keys)
    key_list = ", ".join(quoted)
    before_relation = relation_sql(adapter, before)
    after_relation = relation_sql(adapter, after)
    join = _null_safe_join("b", "a", quoted)
    base_ctes = f"""WITH
b AS (SELECT {key_list}, COUNT(*) AS before_count FROM {before_relation} GROUP BY {key_list}),
a AS (SELECT {key_list}, COUNT(*) AS after_count FROM {after_relation} GROUP BY {key_list}),
aligned AS (
  SELECT {", ".join(f"COALESCE(b.{key}, a.{key}) AS {key}" for key in quoted)},
         COALESCE(before_count, 0) AS before_count,
         COALESCE(after_count, 0) AS after_count
  FROM b FULL OUTER JOIN a ON {join}
)"""
    sql = f"""{base_ctes}
SELECT
  COUNT(*) FILTER (WHERE after_count > before_count) AS affected_keys,
  COALESCE(SUM(after_count - before_count) FILTER (WHERE after_count > before_count), 0)
    AS added_rows,
  COALESCE(MAX(before_count), 0) AS before_maximum_multiplicity,
  COALESCE(MAX(after_count), 0) AS after_maximum_multiplicity
FROM aligned"""
    row = first_row_dict(adapter, sql)
    affected_keys = int(row.get("affected_keys", 0))
    added_rows = int(row.get("added_rows", 0))
    before_max = int(row.get("before_maximum_multiplicity", 0))
    after_max = int(row.get("after_maximum_multiplicity", 0))
    sample_sql = f"""{base_ctes}
SELECT *, after_count - before_count AS added_rows
FROM aligned WHERE after_count > before_count
ORDER BY added_rows DESC, {key_list} NULLS FIRST LIMIT $sample_limit"""
    sample = row_dicts(adapter, sample_sql, parameters=parameters, max_rows=limit)
    measure_inflation: dict[str, float] = {}
    measure_sql: dict[str, str] = {}
    for measure in measures:
        value_sql = f"""WITH
b AS (SELECT {key_list}, COUNT(*) AS n, {measure.expression} AS value
      FROM {before_relation} GROUP BY {key_list}),
a AS (SELECT {key_list}, COUNT(*) AS n, {measure.expression} AS value
      FROM {after_relation} GROUP BY {key_list}),
aligned AS (
  SELECT COALESCE(b.n, 0) AS before_count, COALESCE(a.n, 0) AS after_count,
         b.value AS before_value, a.value AS after_value
  FROM b FULL OUTER JOIN a ON {join}
)
SELECT COALESCE(SUM(after_value - before_value)
  FILTER (WHERE after_count > before_count), 0) AS measure_inflation
FROM aligned"""
        measure_row = first_row_dict(adapter, value_sql)
        measure_inflation[measure.name] = float(measure_row.get("measure_inflation", 0) or 0)
        measure_sql[measure.name] = value_sql
    has_inflation = any(value != 0 for value in measure_inflation.values())
    if before_max <= 1 < after_max:
        pattern = "one_to_many"
    elif before_max > 1 and after_max > before_max:
        pattern = "many_to_many"
    elif affected_keys:
        pattern = "undeclared_grain"
    else:
        pattern = "no_expansion"
    confirmed = affected_keys > 0 and added_rows > 0 and has_inflation
    if confirmed:
        code = "join_fanout"
        status = FindingStatus.FAILURE
        message = "Row multiplication is correlated with measure inflation."
        classification = "confirmed"
    elif affected_keys:
        code = "potentially_legitimate_expansion"
        status = FindingStatus.WARNING
        message = "The grain expanded without sufficient evidence to call it a bug."
        classification = "hypothesis"
    else:
        code = "no_fanout"
        status = FindingStatus.INFO
        message = "No increase in business-key multiplicity was detected."
        classification = "confirmed"
    fanout = finding(
        code=code,
        status=status,
        message=message,
        sql=sql,
        sample_sql=sample_sql,
        evidence={
            "pattern": pattern,
            "affected_keys": affected_keys,
            "added_rows": added_rows,
            "before_maximum_multiplicity": before_max,
            "after_maximum_multiplicity": after_max,
            "measure_inflation": measure_inflation,
            "sample": sample,
        },
        classification=classification,
        execution_metadata={
            "sample_limit": limit,
            "samples_bounded": True,
            "bound_parameters": bound_parameter_metadata(parameters),
        },
        metadata={"measure_sql": measure_sql},
    )
    return before_grain, after_grain, fanout
