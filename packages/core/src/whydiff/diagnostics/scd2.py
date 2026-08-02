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
)
from .keys import _limit, _null_safe_join


def inspect_scd2_alignment(
    adapter: Any,
    fact: Relation | str,
    dimension: Relation | str,
    business_keys: tuple[str, ...] | list[str],
    event_timestamp: str,
    valid_from: str,
    valid_to: str,
    *,
    end_inclusive: bool = False,
    sample_limit: int = 100,
) -> tuple[DiagnosticFinding, ...]:
    limit = _limit(sample_limit)
    parameters: dict[str, object] = {"sample_limit": limit}
    keys = quoted_columns(adapter, business_keys)
    event = quoted_columns(adapter, (event_timestamp,))[0]
    start = quoted_columns(adapter, (valid_from,))[0]
    end = quoted_columns(adapter, (valid_to,))[0]
    fact_relation = relation_sql(adapter, fact)
    dimension_relation = relation_sql(adapter, dimension)
    key_join = _null_safe_join("f", "d", keys)
    end_operator = "<=" if end_inclusive else "<"
    overlap_operator = "<=" if end_inclusive else "<"
    order_keys = ", ".join((*keys, event))
    ctes = f"""WITH
f AS (
  SELECT ROW_NUMBER() OVER (ORDER BY {order_keys} NULLS FIRST) AS __fact_id, *
  FROM {fact_relation}
),
d AS (
  SELECT ROW_NUMBER() OVER (ORDER BY {", ".join((*keys, start, end))} NULLS FIRST)
           AS __dimension_id,
         *, 1 AS __dimension_present
  FROM {dimension_relation}
),
matches AS (
  SELECT f.__fact_id, COUNT(d.__dimension_present) AS match_count
  FROM f LEFT JOIN d ON {key_join}
    AND f.{event} >= d.{start}
    AND (f.{event} {end_operator} d.{end} OR d.{end} IS NULL)
  GROUP BY f.__fact_id
),
overlap_pairs AS (
  SELECT d1.__dimension_id AS left_version_id, d2.__dimension_id AS right_version_id
  FROM d d1 INNER JOIN d d2
    ON d1.__dimension_id < d2.__dimension_id
    AND {_null_safe_join("d1", "d2", keys)}
    AND d1.{start} {overlap_operator} COALESCE(d2.{end}, TIMESTAMP 'infinity')
    AND d2.{start} {overlap_operator} COALESCE(d1.{end}, TIMESTAMP 'infinity')
),
boundary_facts AS (
  SELECT DISTINCT f.__fact_id
  FROM f INNER JOIN d ON {key_join} AND f.{event} = d.{end}
)"""
    sql = f"""{ctes}
SELECT
  COUNT(*) FILTER (WHERE match_count = 0) AS no_match_facts,
  COUNT(*) FILTER (WHERE match_count > 1) AS multiple_match_facts,
  COUNT(*) FILTER (WHERE match_count = 1) AS matched_facts,
  (SELECT COUNT(*) FROM overlap_pairs) AS overlapping_range_pairs,
  (SELECT COUNT(*) FROM boundary_facts) AS exact_end_boundary_facts,
  (SELECT COUNT(*) FROM d WHERE {end} IS NULL) AS open_ended_dimension_rows
FROM matches"""
    row = first_row_dict(adapter, sql)
    evidence: dict[str, Any] = {
        "no_match_facts": int(row.get("no_match_facts", 0)),
        "multiple_match_facts": int(row.get("multiple_match_facts", 0)),
        "matched_facts": int(row.get("matched_facts", 0)),
        "overlapping_range_pairs": int(row.get("overlapping_range_pairs", 0)),
        "exact_end_boundary_facts": int(row.get("exact_end_boundary_facts", 0)),
        "open_ended_dimension_rows": int(row.get("open_ended_dimension_rows", 0)),
        "end_inclusive": end_inclusive,
    }
    fact_projection = ", ".join(f"f.{key} AS {key}" for key in keys)
    no_match_sql = f"""{ctes}
SELECT {fact_projection}, f.{event} AS event_timestamp, m.match_count
FROM f INNER JOIN matches m USING (__fact_id)
WHERE m.match_count = 0 ORDER BY f.__fact_id LIMIT $sample_limit"""
    multiple_sql = f"""{ctes}
SELECT {fact_projection}, f.{event} AS event_timestamp, m.match_count
FROM f INNER JOIN matches m USING (__fact_id)
WHERE m.match_count > 1 ORDER BY m.match_count DESC, f.__fact_id LIMIT $sample_limit"""
    overlap_sql = f"""{ctes}
SELECT o.*, {", ".join(f"d1.{key} AS {key}" for key in keys)},
       d1.{start} AS left_valid_from, d1.{end} AS left_valid_to,
       d2.{start} AS right_valid_from, d2.{end} AS right_valid_to
FROM overlap_pairs o
INNER JOIN d d1 ON d1.__dimension_id = o.left_version_id
INNER JOIN d d2 ON d2.__dimension_id = o.right_version_id
ORDER BY o.left_version_id, o.right_version_id LIMIT $sample_limit"""
    boundary_sql = f"""{ctes}
SELECT {fact_projection}, f.{event} AS event_timestamp
FROM boundary_facts b INNER JOIN f USING (__fact_id)
ORDER BY f.__fact_id LIMIT $sample_limit"""
    findings: list[DiagnosticFinding] = []

    def add_failure(code: str, count_key: str, message: str, sample_query: str) -> None:
        item_evidence = dict(evidence)
        item_evidence["sample"] = row_dicts(
            adapter, sample_query, parameters=parameters, max_rows=limit
        )
        findings.append(
            finding(
                code=code,
                status=FindingStatus.FAILURE,
                message=message,
                sql=sql,
                sample_sql=sample_query,
                evidence=item_evidence,
                classification="confirmed",
                execution_metadata={
                    "sample_limit": limit,
                    "samples_bounded": True,
                    "bound_parameters": bound_parameter_metadata(parameters),
                },
                metadata={"affected_rows_field": count_key},
            )
        )

    if evidence["overlapping_range_pairs"]:
        add_failure(
            "scd2_overlapping_ranges",
            "overlapping_range_pairs",
            "Dimension effective-date ranges overlap for the same business key.",
            overlap_sql,
        )
    if evidence["multiple_match_facts"]:
        add_failure(
            "scd2_multiple_match",
            "multiple_match_facts",
            "One or more facts match multiple dimension versions.",
            multiple_sql,
        )
    if evidence["no_match_facts"]:
        add_failure(
            "scd2_no_match",
            "no_match_facts",
            "One or more facts do not match an effective dimension version.",
            no_match_sql,
        )
    if evidence["exact_end_boundary_facts"]:
        boundary_evidence = dict(evidence)
        boundary_evidence["sample"] = row_dicts(
            adapter, boundary_sql, parameters=parameters, max_rows=limit
        )
        findings.append(
            finding(
                code="scd2_boundary_mismatch",
                status=FindingStatus.WARNING,
                message="Facts occur exactly at a dimension end boundary; verify end semantics.",
                sql=sql,
                sample_sql=boundary_sql,
                evidence=boundary_evidence,
                classification="confirmed",
                execution_metadata={
                    "sample_limit": limit,
                    "samples_bounded": True,
                    "bound_parameters": bound_parameter_metadata(parameters),
                },
            )
        )
    if not findings:
        findings.append(
            finding(
                code="scd2_alignment_match",
                status=FindingStatus.INFO,
                message="Every fact matches exactly one effective dimension version.",
                sql=sql,
                evidence=evidence,
                classification="confirmed",
                execution_metadata={"sample_limit": limit, "samples_bounded": True},
            )
        )
    return tuple(findings)
