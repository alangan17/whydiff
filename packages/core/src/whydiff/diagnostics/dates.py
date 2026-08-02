from __future__ import annotations

from datetime import date, datetime
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
from .keys import _limit


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def inspect_date_boundaries(
    adapter: Any,
    left: Relation | str,
    right: Relation | str,
    timestamp_column: str,
    *,
    window_days: int = 3,
    sample_limit: int = 100,
) -> tuple[DiagnosticFinding, ...]:
    if not 0 <= window_days <= 366:
        raise ValueError("window_days must be between 0 and 366")
    limit = _limit(sample_limit)
    column = quoted_columns(adapter, (timestamp_column,))[0]
    left_relation = relation_sql(adapter, left)
    right_relation = relation_sql(adapter, right)
    ctes = f"""WITH
l_counts AS (
  SELECT CAST({column} AS DATE) AS event_date, COUNT(*) AS row_count
  FROM {left_relation} GROUP BY event_date
),
r_counts AS (
  SELECT CAST({column} AS DATE) AS event_date, COUNT(*) AS row_count
  FROM {right_relation} GROUP BY event_date
),
daily AS (
  SELECT COALESCE(l.event_date, r.event_date) AS event_date,
         COALESCE(l.row_count, 0) AS left_count,
         COALESCE(r.row_count, 0) AS right_count
  FROM l_counts l FULL OUTER JOIN r_counts r USING (event_date)
),
overlap AS (
  SELECT
    COALESCE(SUM(LEAST(l.row_count, r.row_count)), 0) AS same_date_overlap,
    COALESCE(SUM(LEAST(l.row_count, next_r.row_count)), 0) AS plus_one_day_overlap,
    COALESCE(SUM(LEAST(l.row_count, previous_r.row_count)), 0) AS minus_one_day_overlap
  FROM l_counts l
  LEFT JOIN r_counts r ON r.event_date = l.event_date
  LEFT JOIN r_counts next_r ON next_r.event_date = l.event_date + INTERVAL 1 DAY
  LEFT JOIN r_counts previous_r ON previous_r.event_date = l.event_date - INTERVAL 1 DAY
)"""
    sql = f"""{ctes}
SELECT
  (SELECT MIN(CAST({column} AS DATE)) FROM {left_relation}) AS left_min_date,
  (SELECT MAX(CAST({column} AS DATE)) FROM {left_relation}) AS left_max_date,
  (SELECT MIN(CAST({column} AS DATE)) FROM {right_relation}) AS right_min_date,
  (SELECT MAX(CAST({column} AS DATE)) FROM {right_relation}) AS right_max_date,
  MIN(event_date) FILTER (WHERE left_count <> right_count) AS first_divergent_date,
  COUNT(*) FILTER (WHERE left_count <> right_count) AS divergent_dates,
  (SELECT same_date_overlap FROM overlap) AS same_date_overlap,
  (SELECT plus_one_day_overlap FROM overlap) AS plus_one_day_overlap,
  (SELECT minus_one_day_overlap FROM overlap) AS minus_one_day_overlap,
  (SELECT COUNT(*) FILTER (WHERE CAST({column} AS TIMESTAMP) <>
      date_trunc('day', CAST({column} AS TIMESTAMP))) FROM {left_relation})
    AS left_non_midnight_rows,
  (SELECT COUNT(*) FILTER (WHERE CAST({column} AS TIMESTAMP) <>
      date_trunc('day', CAST({column} AS TIMESTAMP))) FROM {right_relation})
    AS right_non_midnight_rows
FROM daily"""
    row = first_row_dict(adapter, sql)
    names = ("left_min_date", "left_max_date", "right_min_date", "right_max_date")
    evidence: dict[str, Any] = {name: _iso(row.get(name)) for name in names}
    first_divergent = _iso(row.get("first_divergent_date"))
    evidence.update(
        {
            "first_divergent_date": first_divergent,
            "divergent_dates": int(row.get("divergent_dates", 0)),
            "same_date_overlap": int(row.get("same_date_overlap", 0)),
            "plus_one_day_overlap": int(row.get("plus_one_day_overlap", 0)),
            "minus_one_day_overlap": int(row.get("minus_one_day_overlap", 0)),
            "left_non_midnight_rows": int(row.get("left_non_midnight_rows", 0)),
            "right_non_midnight_rows": int(row.get("right_non_midnight_rows", 0)),
        }
    )
    sample_sql: str | None = None
    sample_parameters: dict[str, object] = {}
    if first_divergent is not None:
        sample_parameters = {
            "boundary_date": first_divergent,
            "sample_limit": limit,
            "window_days": window_days,
        }
        sample_sql = f"""{ctes}
SELECT * FROM daily
WHERE event_date BETWEEN CAST($boundary_date AS DATE) - $window_days * INTERVAL 1 DAY
  AND CAST($boundary_date AS DATE) + $window_days * INTERVAL 1 DAY
ORDER BY event_date LIMIT $sample_limit"""
        evidence["boundary_counts"] = row_dicts(
            adapter,
            sample_sql,
            parameters=sample_parameters,
            max_rows=limit,
        )
    else:
        evidence["boundary_counts"] = []

    diverged = evidence["divergent_dates"] > 0
    max_dates_differ = evidence["left_max_date"] != evidence["right_max_date"]
    max_dates = [
        value
        for value in (evidence["left_max_date"], evidence["right_max_date"])
        if isinstance(value, str)
    ]
    tail_cutoff = (
        max_dates_differ
        and isinstance(first_divergent, str)
        and len(max_dates) == 2
        and min(max_dates) < first_divergent <= max(max_dates)
    )
    shifted = max(evidence["plus_one_day_overlap"], evidence["minus_one_day_overlap"])
    if not diverged:
        code = "date_boundaries_match"
        status = FindingStatus.INFO
        message = "Date boundaries and daily counts match."
        classification = "confirmed"
    elif tail_cutoff:
        code = "extraction_cutoff"
        status = FindingStatus.FAILURE
        message = "Daily counts diverge at the extraction range cutoff."
        classification = "hypothesis"
    elif shifted > evidence["same_date_overlap"]:
        code = "timezone_date_shift"
        status = FindingStatus.WARNING
        message = "Daily counts align better after a one-day shift; timezone conversion is likely."
        classification = "hypothesis"
    elif (evidence["left_non_midnight_rows"] == 0) != (evidence["right_non_midnight_rows"] == 0):
        code = "date_truncation"
        status = FindingStatus.WARNING
        message = "Only one side preserves sub-day timestamp values."
        classification = "hypothesis"
    else:
        code = "date_boundary_difference"
        status = FindingStatus.FAILURE
        message = "Daily counts differ around a date boundary."
        classification = "confirmed"
    return (
        finding(
            code=code,
            status=status,
            message=message,
            sql=sql,
            sample_sql=sample_sql,
            evidence=evidence,
            classification=classification,
            execution_metadata={
                "window_days": window_days,
                "sample_limit": limit,
                "samples_bounded": True,
                "bound_parameters": bound_parameter_metadata(sample_parameters),
            },
        ),
    )
