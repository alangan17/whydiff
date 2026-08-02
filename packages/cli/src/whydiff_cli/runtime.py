from __future__ import annotations

from typing import Any

from whydiff import MeasureConfig, ReconcileRequest, Relation

from .config import CommandConfig, ConfigurationError


def relation(value: str) -> Relation:
    parts = value.split(".")
    try:
        if len(parts) == 1:
            return Relation(name=parts[0])
        if len(parts) == 2:
            return Relation(schema_name=parts[0], name=parts[1])
        if len(parts) == 3:
            return Relation(catalog=parts[0], schema_name=parts[1], name=parts[2])
    except ValueError as exc:
        raise ConfigurationError(f"invalid relation name: {value}") from exc
    raise ConfigurationError(f"invalid relation name: {value}")


def _jsonable(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        dumped = model.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if isinstance(model, dict):
        return model
    raise TypeError(f"unsupported result type: {type(model).__name__}")


def _normalize_finding(result: Any) -> dict[str, Any]:
    payload = _jsonable(result)
    metadata = payload.get("metadata", {})
    evidence = payload.get("evidence") or metadata.get("evidence", {})
    payload["evidence"] = evidence
    payload["generated_sql"] = payload.get("generated_sql") or metadata.get("sql")
    summary = evidence.get("summary") if isinstance(evidence, dict) else None
    samples = evidence.get("samples") if isinstance(evidence, dict) else None
    if summary is not None:
        payload["summary"] = summary
    elif isinstance(evidence, dict):
        names = ("matched", "left_only", "right_only", "duplicate_groups", "mismatched")
        compact = {name: evidence[name] for name in names if isinstance(evidence.get(name), int)}
        if compact:
            payload["summary"] = compact
        coverage_names = {
            "matched_distinct_keys": "matched",
            "left_only_distinct_keys": "left_only",
            "right_only_distinct_keys": "right_only",
        }
        coverage = {
            public: evidence[source]
            for source, public in coverage_names.items()
            if source in evidence
        }
        if coverage:
            payload["summary"] = coverage
    if samples is not None:
        payload["samples"] = samples
    elif isinstance(evidence, dict):
        compact_samples = {
            name: evidence[name]
            for name in (
                "left_only_sample",
                "right_only_sample",
                "duplicate_sample",
                "mismatch_sample",
            )
            if name in evidence
        }
        if compact_samples:
            payload["samples"] = {
                name.removesuffix("_sample"): value for name, value in compact_samples.items()
            }
    status = payload.get("status")
    payload["status"] = getattr(status, "value", status)
    if payload.get("status") in {"failure", "warning"}:
        payload["status"] = "failed"
    elif payload.get("status") == "info":
        payload["status"] = "passed"
    return payload


def _normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, (list, tuple)):
        findings = [_normalize_finding(item) for item in result]
        failed = any(item.get("status") == "failed" for item in findings)
        return {"status": "failed" if failed else "passed", "findings": findings}
    return _normalize_finding(result)


def _reject_unsafe_findings(payload: dict[str, Any]) -> dict[str, Any]:
    from whydiff.adapters import UnsafeStatementError

    findings = payload.get("findings", [payload])
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("code") != "invalid_measure":
                continue
            evidence = finding.get("evidence", {})
            if isinstance(evidence, dict) and evidence.get("error_type") in {
                "MultipleStatementsError",
                "SQLSafetyError",
                "UnsafeStatementError",
            }:
                raise UnsafeStatementError("measure expression was rejected by SQL safety")
    return payload


def run_operation(operation: str, config: CommandConfig) -> dict[str, Any]:
    from whydiff.adapters import DuckDBAdapter
    from whydiff.diagnostics import (
        compare_key_coverage,
        compare_numeric_measures,
        compare_schema,
        detect_duplicate_keys,
        inspect_relation,
    )

    adapter = DuckDBAdapter(config.database, default_timeout_seconds=config.timeout_seconds)
    try:
        left = relation(config.left) if config.left else None
        right = relation(config.right) if config.right else None
        target = relation(config.relation) if config.relation else left
        if operation == "compare-keys":
            if left is None or right is None or not config.keys:
                raise ConfigurationError("left, right, and at least one key are required")
            return _normalize_result(
                compare_key_coverage(
                    adapter, left, right, config.keys, sample_limit=config.sample_limit
                )
            )
        if operation == "detect-duplicates":
            if target is None or not config.keys:
                raise ConfigurationError("relation and at least one key are required")
            return _normalize_result(
                detect_duplicate_keys(
                    adapter, target, config.keys, sample_limit=config.sample_limit
                )
            )
        if operation == "inspect-schema":
            if left is None and target is None:
                raise ConfigurationError("a relation is required")
            if right is not None:
                if left is None:
                    raise ConfigurationError("left is required when right is configured")
                finding = compare_schema(adapter, left, right)
            else:
                if target is None:
                    raise ConfigurationError("a relation is required")
                finding = inspect_relation(adapter, target)
            return _normalize_result(finding)
        if operation == "compare-measures":
            if left is None or right is None or not config.keys or not config.measures:
                raise ConfigurationError("left, right, keys, and measures are required")
            measures = [
                MeasureConfig(
                    name=item.name,
                    expression=item.expression,
                    absolute_tolerance=item.absolute_tolerance,
                    relative_tolerance=item.relative_tolerance,
                )
                for item in config.measures
            ]
            return _reject_unsafe_findings(
                _normalize_result(
                    compare_numeric_measures(
                        adapter,
                        left,
                        right,
                        config.keys,
                        measures,
                        null_equals_zero=config.null_equals_zero,
                        sample_limit=config.sample_limit,
                    )
                )
            )
        if operation == "detect-fanout":
            from whydiff.diagnostics import detect_fanout

            if left is None or right is None or not config.keys:
                raise ConfigurationError("before, after, and at least one key are required")
            measures = [
                MeasureConfig(
                    name=item.name,
                    expression=item.expression,
                    absolute_tolerance=item.absolute_tolerance,
                    relative_tolerance=item.relative_tolerance,
                )
                for item in config.measures
            ]
            return _normalize_result(
                detect_fanout(
                    adapter,
                    left,
                    right,
                    config.keys,
                    measures=measures,
                    sample_limit=config.sample_limit,
                )
            )
        if operation == "inspect-dates":
            from whydiff.diagnostics import inspect_date_boundaries

            if left is None or right is None or not config.timestamp_column:
                raise ConfigurationError("left, right, and timestamp_column are required")
            return _normalize_result(
                inspect_date_boundaries(
                    adapter,
                    left,
                    right,
                    config.timestamp_column,
                    window_days=config.window_days,
                    sample_limit=config.sample_limit,
                )
            )
        if operation == "inspect-scd2":
            from whydiff.diagnostics import inspect_scd2_alignment

            if (
                left is None
                or right is None
                or not config.keys
                or not config.event_timestamp
                or not config.valid_from
                or not config.valid_to
            ):
                raise ConfigurationError(
                    "fact, dimension, keys, event_timestamp, valid_from, and valid_to are required"
                )
            return _normalize_result(
                inspect_scd2_alignment(
                    adapter,
                    left,
                    right,
                    config.keys,
                    config.event_timestamp,
                    config.valid_from,
                    config.valid_to,
                    end_inclusive=config.end_inclusive,
                    sample_limit=config.sample_limit,
                )
            )
        if operation == "diagnose":
            from whydiff.diagnostics import diagnose

            if left is None or right is None or not config.keys:
                raise ConfigurationError("left, right, and at least one key are required")
            request = ReconcileRequest(
                left=left,
                right=right,
                unique_keys=list(config.keys),
                measures=[
                    MeasureConfig(
                        name=item.name,
                        expression=item.expression,
                        absolute_tolerance=item.absolute_tolerance,
                        relative_tolerance=item.relative_tolerance,
                    )
                    for item in config.measures
                ],
                sample_limit=config.sample_limit,
                null_equals_zero=config.null_equals_zero,
            )
            payload = _jsonable(diagnose(adapter, request))
            status = payload.get("status")
            payload["status"] = getattr(status, "value", status)
            return payload
        raise ConfigurationError(f"unknown operation: {operation}")
    finally:
        adapter.close()
