from __future__ import annotations

from typing import Any

from whydiff.models import DiagnosticFinding, FindingStatus, Relation

from ._support import (
    bound_parameter_metadata,
    finding,
    first_row_dict,
    quoted_columns,
    relation_sql,
    row_dicts,
    value_from,
)


def _limit(sample_limit: int) -> int:
    if not 1 <= sample_limit <= 10_000:
        raise ValueError("sample_limit must be between 1 and 10000")
    return sample_limit


def _null_safe_join(left_alias: str, right_alias: str, keys: tuple[str, ...]) -> str:
    return " AND ".join(
        f"{left_alias}.{key} IS NOT DISTINCT FROM {right_alias}.{key}" for key in keys
    )


def compare_key_coverage(
    adapter: Any,
    left: Relation | str,
    right: Relation | str,
    keys: tuple[str, ...] | list[str],
    *,
    sample_limit: int = 100,
) -> DiagnosticFinding:
    limit = _limit(sample_limit)
    parameters: dict[str, object] = {"sample_limit": limit}
    quoted = quoted_columns(adapter, keys)
    key_list = ", ".join(quoted)
    left_relation = relation_sql(adapter, left)
    right_relation = relation_sql(adapter, right)
    join = _null_safe_join("l", "r", quoted)
    sql = f"""WITH
__left_keys AS (SELECT DISTINCT {key_list}, 1 AS __left_present FROM {left_relation}),
__right_keys AS (SELECT DISTINCT {key_list}, 1 AS __right_present FROM {right_relation}),
coverage AS (
  SELECT l.__left_present, r.__right_present
  FROM __left_keys l FULL OUTER JOIN __right_keys r ON {join}
)
SELECT
  (SELECT COUNT(*) FROM {left_relation}) AS left_physical_rows,
  (SELECT COUNT(*) FROM {right_relation}) AS right_physical_rows,
  (SELECT COUNT(*) FROM __left_keys) AS left_distinct_keys,
  (SELECT COUNT(*) FROM __right_keys) AS right_distinct_keys,
  COUNT(*) FILTER (WHERE __left_present = 1 AND __right_present = 1) AS matched_distinct_keys,
  COUNT(*) FILTER (WHERE __left_present = 1 AND __right_present IS NULL)
    AS left_only_distinct_keys,
  COUNT(*) FILTER (WHERE __left_present IS NULL AND __right_present = 1)
    AS right_only_distinct_keys
FROM coverage"""
    row = first_row_dict(adapter, sql)
    evidence: dict[str, Any] = {
        name: int(value_from(row, name, position))
        for position, name in enumerate(
            (
                "left_physical_rows",
                "right_physical_rows",
                "left_distinct_keys",
                "right_distinct_keys",
                "matched_distinct_keys",
                "left_only_distinct_keys",
                "right_only_distinct_keys",
            )
        )
    }
    left_total = evidence["left_distinct_keys"]
    right_total = evidence["right_distinct_keys"]
    matched = evidence["matched_distinct_keys"]
    evidence["left_coverage_percentage"] = (
        100.0 if left_total == 0 else round(matched * 100.0 / left_total, 6)
    )
    evidence["right_coverage_percentage"] = (
        100.0 if right_total == 0 else round(matched * 100.0 / right_total, 6)
    )
    left_sample_sql = f"""WITH l AS (SELECT DISTINCT {key_list} FROM {left_relation}),
r AS (SELECT DISTINCT {key_list} FROM {right_relation})
SELECT l.* FROM l
WHERE NOT EXISTS (SELECT 1 FROM r WHERE {_null_safe_join("l", "r", quoted)})
ORDER BY {", ".join(f"l.{key}" for key in quoted)} NULLS FIRST
LIMIT $sample_limit"""
    right_sample_sql = f"""WITH l AS (SELECT DISTINCT {key_list} FROM {left_relation}),
r AS (SELECT DISTINCT {key_list} FROM {right_relation})
SELECT r.* FROM r
WHERE NOT EXISTS (SELECT 1 FROM l WHERE {_null_safe_join("l", "r", quoted)})
ORDER BY {", ".join(f"r.{key}" for key in quoted)} NULLS FIRST
LIMIT $sample_limit"""
    evidence["left_only_sample"] = row_dicts(
        adapter, left_sample_sql, parameters=parameters, max_rows=limit
    )
    evidence["right_only_sample"] = row_dicts(
        adapter, right_sample_sql, parameters=parameters, max_rows=limit
    )
    differs = bool(evidence["left_only_distinct_keys"] or evidence["right_only_distinct_keys"])
    return finding(
        code="key_coverage_mismatch" if differs else "key_coverage_match",
        status=FindingStatus.FAILURE if differs else FindingStatus.INFO,
        message="Business-key coverage differs between relations."
        if differs
        else "Business-key coverage matches.",
        sql=sql,
        sample_sql=(left_sample_sql, right_sample_sql),
        evidence=evidence,
        classification="confirmed",
        execution_metadata={
            "sample_limit": limit,
            "samples_bounded": True,
            "bound_parameters": bound_parameter_metadata(parameters),
        },
    )


def detect_duplicate_keys(
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
  COUNT(*) FILTER (WHERE multiplicity > 1) AS duplicate_groups,
  COALESCE(SUM(multiplicity) FILTER (WHERE multiplicity > 1), 0) AS duplicated_physical_rows,
  COALESCE(SUM(multiplicity - 1) FILTER (WHERE multiplicity > 1), 0) AS excess_rows,
  COALESCE(MAX(multiplicity), 0) AS maximum_multiplicity
FROM grouped"""
    row = first_row_dict(adapter, sql)
    evidence: dict[str, Any] = {
        name: int(value_from(row, name, position) or 0)
        for position, name in enumerate(
            (
                "duplicate_groups",
                "duplicated_physical_rows",
                "excess_rows",
                "maximum_multiplicity",
            )
        )
    }
    sample_sql = f"""WITH grouped AS ({grouped})
SELECT * FROM grouped WHERE multiplicity > 1
ORDER BY multiplicity DESC, {key_list} NULLS FIRST
LIMIT $sample_limit"""
    evidence["sample"] = row_dicts(adapter, sample_sql, parameters=parameters, max_rows=limit)
    evidence["side"] = side
    duplicated = evidence["duplicate_groups"] > 0
    return finding(
        code="duplicate_business_keys" if duplicated else "business_grain_match",
        status=FindingStatus.FAILURE if duplicated else FindingStatus.INFO,
        message=f"{side.capitalize()} relation violates the declared business grain."
        if duplicated
        else f"{side.capitalize()} relation matches the declared business grain.",
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
