from __future__ import annotations

from decimal import Decimal
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


def _validated_tolerance(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        raise ValueError("tolerances must be finite and non-negative")
    return value


def compare_numeric_measures(
    adapter: Any,
    left: Relation | str,
    right: Relation | str,
    keys: tuple[str, ...] | list[str],
    measures: tuple[MeasureConfig, ...] | list[MeasureConfig],
    *,
    null_equals_zero: bool = False,
    sample_limit: int = 100,
) -> tuple[DiagnosticFinding, ...]:
    limit = _limit(sample_limit)
    quoted_keys = quoted_columns(adapter, keys)
    key_list = ", ".join(quoted_keys)
    left_relation = relation_sql(adapter, left)
    right_relation = relation_sql(adapter, right)
    join = _null_safe_join("l", "r", quoted_keys)
    findings: list[DiagnosticFinding] = []
    for measure in measures:
        # The adapter validates the complete SELECT. Measure expressions are intentionally
        # SQL expressions because aggregate definitions such as SUM(amount) are public input.
        expression = measure.expression
        tolerance_parameters: dict[str, object] = {
            "absolute_tolerance": _validated_tolerance(measure.absolute_tolerance),
            "relative_tolerance": _validated_tolerance(measure.relative_tolerance),
        }
        sample_parameters = tolerance_parameters | {"sample_limit": limit}
        left_value = "COALESCE(l.__value, 0)" if null_equals_zero else "l.__value"
        right_value = "COALESCE(r.__value, 0)" if null_equals_zero else "r.__value"
        absolute_difference = f"ABS(({left_value}) - ({right_value}))"
        denominator = f"GREATEST(ABS({left_value}), ABS({right_value}))"
        relative_difference = (
            f"CASE WHEN {denominator} = 0 THEN 0 ELSE {absolute_difference} / {denominator} END"
        )
        null_mismatch = (
            "FALSE" if null_equals_zero else "((l.__value IS NULL) <> (r.__value IS NULL))"
        )
        both_null = "FALSE" if null_equals_zero else "(l.__value IS NULL AND r.__value IS NULL)"
        finite = (
            f"isfinite(CAST({left_value} AS DOUBLE)) AND isfinite(CAST({right_value} AS DOUBLE))"
        )
        nonfinite_equal = f"({left_value}) IS NOT DISTINCT FROM ({right_value})"
        ctes = f"""WITH
l AS (SELECT {key_list}, {expression} AS __value FROM {left_relation} GROUP BY {key_list}),
r AS (SELECT {key_list}, {expression} AS __value FROM {right_relation} GROUP BY {key_list}),
aligned AS (
  SELECT {", ".join(f"l.{key} AS {key}" for key in quoted_keys)},
         l.__value AS left_value, r.__value AS right_value,
         {null_mismatch} AS null_mismatch,
         {both_null} AS both_null,
         {finite} AS values_finite,
         {absolute_difference} AS absolute_difference,
         {relative_difference} AS relative_difference,
         {nonfinite_equal} AS nonfinite_equal
  FROM l INNER JOIN r ON {join}
),
classified AS (
  SELECT *, CASE
    WHEN both_null OR (values_finite AND absolute_difference = 0) OR
         (NOT values_finite AND nonfinite_equal) THEN 'exact'
    WHEN null_mismatch THEN 'null_mismatch'
    WHEN NOT values_finite THEN 'outside_tolerance'
    WHEN absolute_difference <= $absolute_tolerance
      OR relative_difference <= $relative_tolerance THEN 'tolerated'
    ELSE 'outside_tolerance'
  END AS category
  FROM aligned
)"""
        sql = f"""{ctes}
SELECT
  COUNT(*) AS matched_key_rows,
  COUNT(*) FILTER (WHERE category = 'exact') AS exact_rows,
  COUNT(*) FILTER (WHERE category = 'tolerated') AS tolerated_rows,
  COUNT(*) FILTER (WHERE category = 'outside_tolerance') AS outside_tolerance_rows,
  COUNT(*) FILTER (WHERE category = 'null_mismatch') AS null_mismatch_rows,
  COUNT(*) FILTER (WHERE category IN ('outside_tolerance', 'null_mismatch')) AS affected_rows,
  MAX(absolute_difference) FILTER (WHERE values_finite) AS maximum_absolute_difference,
  MAX(relative_difference) FILTER (WHERE values_finite) AS maximum_relative_difference
FROM classified"""
        try:
            row = first_row_dict(adapter, sql, parameters=tolerance_parameters)
        except Exception as exc:
            findings.append(
                finding(
                    code="invalid_measure",
                    status=FindingStatus.FAILURE,
                    message=f"Measure {measure.name!r} could not be evaluated.",
                    sql=sql,
                    evidence={"measure": measure.name, "error_type": type(exc).__name__},
                    classification="confirmed",
                    execution_metadata={
                        "sample_limit": limit,
                        "samples_bounded": True,
                        "bound_parameters": bound_parameter_metadata(tolerance_parameters),
                    },
                    metadata={"null_equals_zero": null_equals_zero},
                )
            )
            continue
        evidence: dict[str, Any] = {
            "measure": measure.name,
            "matched_key_rows": int(row.get("matched_key_rows", 0)),
            "exact_rows": int(row.get("exact_rows", 0)),
            "tolerated_rows": int(row.get("tolerated_rows", 0)),
            "outside_tolerance_rows": int(row.get("outside_tolerance_rows", 0)),
            "null_mismatch_rows": int(row.get("null_mismatch_rows", 0)),
            "affected_rows": int(row.get("affected_rows", 0)),
            "maximum_absolute_difference": row.get("maximum_absolute_difference"),
            "maximum_relative_difference": row.get("maximum_relative_difference"),
            "absolute_tolerance": measure.absolute_tolerance,
            "relative_tolerance": measure.relative_tolerance,
        }
        sample_sql = f"""{ctes}
SELECT * FROM classified
WHERE category IN ('outside_tolerance', 'null_mismatch')
ORDER BY category, {key_list} NULLS FIRST
LIMIT $sample_limit"""
        evidence["sample"] = row_dicts(
            adapter,
            sample_sql,
            parameters=sample_parameters,
            max_rows=limit,
        )
        mismatched = evidence["affected_rows"] > 0
        if evidence["null_mismatch_rows"] and not evidence["outside_tolerance_rows"]:
            code = "null_handling"
        else:
            code = "measure_mismatch" if mismatched else "measure_match"
        findings.append(
            finding(
                code=code,
                status=FindingStatus.FAILURE if mismatched else FindingStatus.INFO,
                message=f"Measure {measure.name!r} has material differences."
                if mismatched
                else f"Measure {measure.name!r} matches within tolerance.",
                sql=sql,
                sample_sql=sample_sql,
                evidence=evidence,
                classification="confirmed",
                execution_metadata={
                    "sample_limit": limit,
                    "samples_bounded": True,
                    "bound_parameters": bound_parameter_metadata(sample_parameters),
                },
                metadata={"null_equals_zero": null_equals_zero},
            )
        )
    return tuple(findings)
