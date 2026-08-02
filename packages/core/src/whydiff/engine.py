from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue
from typing_extensions import Self

from whydiff.adapters import BaseAdapter, DuckDBAdapter
from whydiff.diagnostics.basic import compare_row_counts, compare_schema, inspect_relation
from whydiff.diagnostics.keys import compare_key_coverage, detect_duplicate_keys
from whydiff.diagnostics.measures import compare_numeric_measures
from whydiff.models import (
    DiagnosisReport,
    DiagnosticFinding,
    FindingStatus,
    ReconcileRequest,
    ReportStatus,
)


def _affected_rows(finding: DiagnosticFinding) -> int:
    for key in ("affected_rows", "excess_rows", "left_only_distinct_keys"):
        value = finding.evidence.get(key)
        if isinstance(value, int):
            return value
    return 0


def _rank(finding: DiagnosticFinding) -> tuple[int, int, str, str]:
    severity = {
        FindingStatus.FAILURE: 0,
        FindingStatus.WARNING: 1,
        FindingStatus.INFO: 2,
    }[finding.status]
    return severity, -_affected_rows(finding), finding.code, finding.message


def _classify(finding: DiagnosticFinding) -> DiagnosticFinding:
    cause_codes: list[str] = []
    if finding.code in {"missing_relation", "missing_columns", "schema_mismatch"}:
        cause_codes.append("schema_mismatch")
    elif finding.code == "key_coverage_mismatch":
        if _json_count(finding.evidence.get("left_only_distinct_keys")):
            cause_codes.append("missing_keys")
        if _json_count(finding.evidence.get("right_only_distinct_keys")):
            cause_codes.append("additional_keys")
    elif finding.code == "duplicate_business_keys":
        cause_codes.append("duplicate_business_keys")
    elif finding.code == "null_handling":
        cause_codes.append("null_handling")
    elif finding.code == "measure_mismatch":
        cause_codes.append("numeric_precision")
    elif finding.code == "row_count_mismatch":
        cause_codes.append("unknown")
    if not cause_codes and finding.status == FindingStatus.FAILURE:
        cause_codes.append("unknown")
    metadata: dict[str, JsonValue] = dict(finding.metadata)
    metadata["cause_codes"] = cast(JsonValue, cause_codes)
    if finding.code == "row_count_mismatch":
        metadata["classification"] = "hypothesis"
    return finding.model_copy(update={"metadata": metadata})


def _json_count(value: JsonValue | None) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def diagnose(adapter: BaseAdapter, request: ReconcileRequest) -> DiagnosisReport:
    requested_columns = tuple(request.unique_keys)
    left_inspection = inspect_relation(adapter, request.left, requested_columns)
    right_inspection = inspect_relation(adapter, request.right, requested_columns)
    findings: list[DiagnosticFinding] = [left_inspection, right_inspection]
    if any(finding.status == FindingStatus.FAILURE for finding in findings):
        classified = sorted((_classify(finding) for finding in findings), key=_rank)
        return DiagnosisReport(status=ReportStatus.FAILED, findings=classified)

    findings.extend(
        (
            compare_schema(adapter, request.left, request.right),
            compare_row_counts(adapter, request.left, request.right),
            compare_key_coverage(
                adapter,
                request.left,
                request.right,
                request.unique_keys,
                sample_limit=request.sample_limit,
            ),
            detect_duplicate_keys(
                adapter,
                request.left,
                request.unique_keys,
                side="left",
                sample_limit=request.sample_limit,
            ),
            detect_duplicate_keys(
                adapter,
                request.right,
                request.unique_keys,
                side="right",
                sample_limit=request.sample_limit,
            ),
        )
    )
    findings.extend(
        compare_numeric_measures(
            adapter,
            request.left,
            request.right,
            request.unique_keys,
            request.measures,
            null_equals_zero=request.null_equals_zero,
            sample_limit=request.sample_limit,
        )
    )
    classified = sorted((_classify(finding) for finding in findings), key=_rank)
    if any(finding.status == FindingStatus.FAILURE for finding in classified):
        status = ReportStatus.FAILED
    elif any(finding.status == FindingStatus.WARNING for finding in classified):
        status = ReportStatus.WARNING
    else:
        status = ReportStatus.PASSED
    return DiagnosisReport(status=status, findings=classified)


class WhyDiff:
    """Public deterministic diagnostics facade over a secure database adapter."""

    def __init__(self, adapter: BaseAdapter) -> None:
        self.adapter = adapter

    @classmethod
    def duckdb(
        cls,
        database: str | Path = ":memory:",
        **adapter_options: Any,
    ) -> Self:
        return cls(DuckDBAdapter(database=database, **adapter_options))

    def diagnose(self, request: ReconcileRequest) -> DiagnosisReport:
        return diagnose(self.adapter, request)

    def close(self) -> None:
        self.adapter.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
