from __future__ import annotations

import fnmatch
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from whydiff import Relation


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectRelationsInput(ToolInput):
    relations: list[str] = Field(min_length=1)
    requested_columns: list[str] = Field(default_factory=list)
    sample_limit: int = Field(default=100, ge=1)


class CompareKeyCoverageInput(ToolInput):
    left: str
    right: str
    keys: list[str] = Field(min_length=1)
    sample_limit: int = Field(default=100, ge=1)


class DetectDuplicateKeysInput(ToolInput):
    relation: str
    keys: list[str] = Field(min_length=1)
    side: Literal["left", "right", "relation"] = "relation"
    sample_limit: int = Field(default=100, ge=1)


class MeasureInput(ToolInput):
    name: str
    expression: str
    absolute_tolerance: str = "0"
    relative_tolerance: str = "0"


class CompareMeasuresInput(ToolInput):
    left: str
    right: str
    keys: list[str] = Field(min_length=1)
    measures: list[MeasureInput] = Field(min_length=1)
    null_equals_zero: bool = False
    sample_limit: int = Field(default=100, ge=1)


class DiagnoseDifferenceInput(CompareMeasuresInput):
    measures: list[MeasureInput] = Field(default_factory=list)


class DetectFanoutInput(ToolInput):
    before: str
    after: str
    keys: list[str] = Field(min_length=1)
    measures: list[MeasureInput] = Field(default_factory=list)
    sample_limit: int = Field(default=100, ge=1)


class InspectDateBoundariesInput(ToolInput):
    left: str
    right: str
    timestamp_column: str
    window_days: int = Field(default=3, ge=0, le=366)
    sample_limit: int = Field(default=100, ge=1)


class InspectSCD2AlignmentInput(ToolInput):
    fact: str
    dimension: str
    business_keys: list[str] = Field(min_length=1)
    event_timestamp: str
    valid_from: str
    valid_to: str
    end_inclusive: bool = False
    sample_limit: int = Field(default=100, ge=1)


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_relations: tuple[str, ...]
    max_sample_rows: int = 100
    timeout_seconds: float = 30.0
    redacted_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.allowed_relations:
            raise ValueError("allowed_relations must not be empty")
        if self.max_sample_rows < 1:
            raise ValueError("max_sample_rows must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    inputSchema: dict[str, Any]  # noqa: N815 - MCP wire protocol spelling


_TOOL_TYPES: dict[str, type[ToolInput]] = {
    "inspect_relations": InspectRelationsInput,
    "compare_key_coverage": CompareKeyCoverageInput,
    "detect_duplicate_keys": DetectDuplicateKeysInput,
    "compare_measures": CompareMeasuresInput,
    "diagnose_difference": DiagnoseDifferenceInput,
    "detect_fanout": DetectFanoutInput,
    "inspect_date_boundaries": InspectDateBoundariesInput,
    "inspect_scd2_alignment": InspectSCD2AlignmentInput,
}

_DESCRIPTIONS = {
    "inspect_relations": (
        "Inspect scoped relation schemas. Use when relation identity or columns are unknown; "
        "do not use to compare values."
    ),
    "compare_key_coverage": (
        "Compare key presence between two scoped relations. Use before measure comparison; "
        "not for duplicate detection."
    ),
    "detect_duplicate_keys": (
        "Find duplicate key groups in one scoped relation. Use when grain may be non-unique; "
        "not for arbitrary SQL."
    ),
    "compare_measures": (
        "Compare configured numeric aggregates on shared keys. Use after key coverage; "
        "not when keys are unknown."
    ),
    "diagnose_difference": (
        "Run the deterministic ordered diagnosis. Use for a complete evidence report; "
        "it never invokes an LLM."
    ),
    "detect_fanout": (
        "Compare grain and configured measures before and after a join. Use for fanout "
        "evidence; not for general key coverage."
    ),
    "inspect_date_boundaries": (
        "Inspect bounded timestamp distributions and extraction cutoffs. Use for date-window "
        "hypotheses; not as proof of timezone intent."
    ),
    "inspect_scd2_alignment": (
        "Inspect fact events against scoped SCD2 validity ranges. Use for gaps, overlaps, and "
        "boundary evidence; not to rewrite history."
    ),
}


def _relation(value: str) -> Relation:
    parts = value.split(".")
    if len(parts) == 1:
        return Relation(name=parts[0])
    if len(parts) == 2:
        return Relation(schema_name=parts[0], name=parts[1])
    if len(parts) == 3:
        return Relation(catalog=parts[0], schema_name=parts[1], name=parts[2])
    raise ValueError(f"invalid relation name: {value}")


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


def _dump_mapping(value: Any) -> dict[str, Any]:
    dumped = _dump(value)
    if not isinstance(dumped, dict):
        raise TypeError(f"expected structured mapping, got {type(dumped).__name__}")
    return dumped


def _reject_unsafe_findings(findings: list[dict[str, Any]]) -> None:
    from whydiff.adapters import UnsafeStatementError

    for finding in findings:
        evidence = finding.get("evidence", {})
        if finding.get("code") == "invalid_measure" and isinstance(evidence, dict):
            if evidence.get("error_type") in {
                "MultipleStatementsError",
                "SQLSafetyError",
                "UnsafeStatementError",
            }:
                raise UnsafeStatementError("measure expression was rejected by SQL safety")


class WhyDiffServer:
    """A transport-independent MCP tool host, suitable for direct client tests."""

    def __init__(self, *, database: str, policy: SecurityPolicy):
        self._database = database
        self.policy = policy

    async def list_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(name, _DESCRIPTIONS[name], model.model_json_schema())
            for name, model in sorted(_TOOL_TYPES.items())
        ]

    def _check_relation(self, relation: str) -> None:
        if not any(
            fnmatch.fnmatchcase(relation, pattern) for pattern in self.policy.allowed_relations
        ):
            raise PermissionError(f"relation {relation!r} is outside the configured scope")

    def _validate_scope(self, model: ToolInput) -> None:
        sample_limit = getattr(model, "sample_limit", 1)
        if sample_limit > self.policy.max_sample_rows:
            raise ValueError(
                f"sample_limit {sample_limit} exceeds policy maximum {self.policy.max_sample_rows}"
            )
        values: list[str] = []
        for field in ("relation", "left", "right", "before", "after", "fact", "dimension"):
            value = getattr(model, field, None)
            if value:
                values.append(value)
        values.extend(getattr(model, "relations", []))
        for value in values:
            self._check_relation(value)

    def _redact(self, value: Any) -> Any:
        redacted = {column.casefold() for column in self.policy.redacted_columns}
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if key.casefold() in redacted else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        model_type = _TOOL_TYPES.get(name)
        if model_type is None:
            raise ValueError(f"unknown tool: {name}")
        model = model_type.model_validate(arguments)
        self._validate_scope(model)
        started = time.monotonic()
        result = self._invoke(name, model)
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        redacted_payload = self._redact(_dump_mapping(result))
        if not isinstance(redacted_payload, dict):
            raise TypeError("redacted tool result is not a mapping")
        payload: dict[str, Any] = redacted_payload
        payload["trace"] = {
            "operation": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "connection_id": hashlib.sha256(self._database.encode()).hexdigest()[:12],
            "sample_limit": getattr(model, "sample_limit", None),
            "sanitized": True,
        }
        return payload

    def _invoke(self, name: str, model: ToolInput) -> dict[str, Any]:
        from whydiff.adapters import DuckDBAdapter
        from whydiff.diagnostics import (
            compare_key_coverage,
            compare_numeric_measures,
            detect_duplicate_keys,
            detect_fanout,
            inspect_date_boundaries,
            inspect_relation,
            inspect_scd2_alignment,
        )

        adapter = DuckDBAdapter(
            self._database,
            default_timeout_seconds=self.policy.timeout_seconds,
            default_max_rows=self.policy.max_sample_rows + 1,
        )
        try:
            if isinstance(model, InspectRelationsInput):
                findings = [
                    inspect_relation(adapter, _relation(item), model.requested_columns)
                    for item in model.relations
                ]
                return {
                    "status": "failed"
                    if any(str(f.status) == "failure" for f in findings)
                    else "passed",
                    "findings": _dump(findings),
                }
            if isinstance(model, CompareKeyCoverageInput):
                return _dump_mapping(
                    compare_key_coverage(
                        adapter,
                        _relation(model.left),
                        _relation(model.right),
                        model.keys,
                        sample_limit=model.sample_limit,
                    )
                )
            if isinstance(model, DetectDuplicateKeysInput):
                return _dump_mapping(
                    detect_duplicate_keys(
                        adapter,
                        _relation(model.relation),
                        model.keys,
                        side=model.side,
                        sample_limit=model.sample_limit,
                    )
                )
            if isinstance(model, CompareMeasuresInput) and not isinstance(
                model, DiagnoseDifferenceInput
            ):
                findings_value = _dump(
                    compare_numeric_measures(
                        adapter,
                        _relation(model.left),
                        _relation(model.right),
                        model.keys,
                        self._measures(model.measures),
                        null_equals_zero=model.null_equals_zero,
                        sample_limit=model.sample_limit,
                    )
                )
                if not isinstance(findings_value, list):
                    raise TypeError("measure comparison did not return findings")
                measure_findings: list[dict[str, Any]] = []
                for item in findings_value:
                    if not isinstance(item, dict):
                        raise TypeError("measure finding is not a mapping")
                    measure_findings.append(item)
                _reject_unsafe_findings(measure_findings)
                return {
                    "status": "failed"
                    if any(item.get("status") == "failure" for item in measure_findings)
                    else "passed",
                    "findings": measure_findings,
                }
            if isinstance(model, DiagnoseDifferenceInput):
                from whydiff import ReconcileRequest
                from whydiff.diagnostics import diagnose

                request = ReconcileRequest(
                    left=_relation(model.left),
                    right=_relation(model.right),
                    unique_keys=model.keys,
                    measures=self._measures(model.measures),
                    null_equals_zero=model.null_equals_zero,
                    sample_limit=model.sample_limit,
                )
                return _dump_mapping(diagnose(adapter, request))
            if isinstance(model, DetectFanoutInput):
                return self._finding_report(
                    detect_fanout(
                        adapter,
                        _relation(model.before),
                        _relation(model.after),
                        model.keys,
                        measures=self._measures(model.measures),
                        sample_limit=model.sample_limit,
                    )
                )
            if isinstance(model, InspectDateBoundariesInput):
                return self._finding_report(
                    inspect_date_boundaries(
                        adapter,
                        _relation(model.left),
                        _relation(model.right),
                        model.timestamp_column,
                        window_days=model.window_days,
                        sample_limit=model.sample_limit,
                    )
                )
            if isinstance(model, InspectSCD2AlignmentInput):
                return self._finding_report(
                    inspect_scd2_alignment(
                        adapter,
                        _relation(model.fact),
                        _relation(model.dimension),
                        model.business_keys,
                        model.event_timestamp,
                        model.valid_from,
                        model.valid_to,
                        end_inclusive=model.end_inclusive,
                        sample_limit=model.sample_limit,
                    )
                )
            raise AssertionError("unreachable tool dispatch")
        finally:
            adapter.close()

    @staticmethod
    def _measures(measures: list[MeasureInput]) -> list[Any]:
        from whydiff import MeasureConfig

        return [MeasureConfig(**item.model_dump()) for item in measures]

    @staticmethod
    def _finding_report(value: Any) -> dict[str, Any]:
        dumped = _dump(value)
        if not isinstance(dumped, list) or not all(isinstance(item, dict) for item in dumped):
            raise TypeError("diagnostic did not return a finding sequence")
        statuses = {item.get("status") for item in dumped}
        if "failure" in statuses:
            status = "failed"
        elif "warning" in statuses:
            status = "warning"
        else:
            status = "passed"
        return {"status": status, "findings": dumped}


def build_fastmcp(server: WhyDiffServer) -> Any:
    """Build the stdio transport without coupling tests to MCP internals."""
    from mcp.server.fastmcp import FastMCP

    transport = FastMCP("whydiff")

    @transport.tool(name="inspect_relations", description=_DESCRIPTIONS["inspect_relations"])
    async def inspect_relations_tool(
        relations: list[str],
        requested_columns: list[str] | None = None,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "inspect_relations",
            {
                "relations": relations,
                "requested_columns": requested_columns or [],
                "sample_limit": sample_limit,
            },
        )

    @transport.tool(name="compare_key_coverage", description=_DESCRIPTIONS["compare_key_coverage"])
    async def compare_key_coverage_tool(
        left: str, right: str, keys: list[str], sample_limit: int = 100
    ) -> dict[str, Any]:
        return await server.call_tool(
            "compare_key_coverage",
            {"left": left, "right": right, "keys": keys, "sample_limit": sample_limit},
        )

    @transport.tool(
        name="detect_duplicate_keys", description=_DESCRIPTIONS["detect_duplicate_keys"]
    )
    async def detect_duplicate_keys_tool(
        relation: str,
        keys: list[str],
        side: Literal["left", "right", "relation"] = "relation",
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "detect_duplicate_keys",
            {"relation": relation, "keys": keys, "side": side, "sample_limit": sample_limit},
        )

    @transport.tool(name="compare_measures", description=_DESCRIPTIONS["compare_measures"])
    async def compare_measures_tool(
        left: str,
        right: str,
        keys: list[str],
        measures: list[MeasureInput],
        null_equals_zero: bool = False,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "compare_measures",
            {
                "left": left,
                "right": right,
                "keys": keys,
                "measures": [item.model_dump() for item in measures],
                "null_equals_zero": null_equals_zero,
                "sample_limit": sample_limit,
            },
        )

    @transport.tool(name="diagnose_difference", description=_DESCRIPTIONS["diagnose_difference"])
    async def diagnose_difference_tool(
        left: str,
        right: str,
        keys: list[str],
        measures: list[MeasureInput] | None = None,
        null_equals_zero: bool = False,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "diagnose_difference",
            {
                "left": left,
                "right": right,
                "keys": keys,
                "measures": [item.model_dump() for item in (measures or [])],
                "null_equals_zero": null_equals_zero,
                "sample_limit": sample_limit,
            },
        )

    @transport.tool(name="detect_fanout", description=_DESCRIPTIONS["detect_fanout"])
    async def detect_fanout_tool(
        before: str,
        after: str,
        keys: list[str],
        measures: list[MeasureInput] | None = None,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "detect_fanout",
            {
                "before": before,
                "after": after,
                "keys": keys,
                "measures": [item.model_dump() for item in (measures or [])],
                "sample_limit": sample_limit,
            },
        )

    @transport.tool(
        name="inspect_date_boundaries", description=_DESCRIPTIONS["inspect_date_boundaries"]
    )
    async def inspect_date_boundaries_tool(
        left: str,
        right: str,
        timestamp_column: str,
        window_days: int = 3,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "inspect_date_boundaries",
            {
                "left": left,
                "right": right,
                "timestamp_column": timestamp_column,
                "window_days": window_days,
                "sample_limit": sample_limit,
            },
        )

    @transport.tool(
        name="inspect_scd2_alignment", description=_DESCRIPTIONS["inspect_scd2_alignment"]
    )
    async def inspect_scd2_alignment_tool(
        fact: str,
        dimension: str,
        business_keys: list[str],
        event_timestamp: str,
        valid_from: str,
        valid_to: str,
        end_inclusive: bool = False,
        sample_limit: int = 100,
    ) -> dict[str, Any]:
        return await server.call_tool(
            "inspect_scd2_alignment",
            {
                "fact": fact,
                "dimension": dimension,
                "business_keys": business_keys,
                "event_timestamp": event_timestamp,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "end_inclusive": end_inclusive,
                "sample_limit": sample_limit,
            },
        )

    return transport


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the read-only WhyDiff MCP server")
    parser.add_argument("--database", required=True)
    parser.add_argument("--allow-relation", action="append", required=True)
    parser.add_argument("--max-sample-rows", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--redact-column", action="append", default=[])
    args = parser.parse_args()
    host = WhyDiffServer(
        database=args.database,
        policy=SecurityPolicy(
            allowed_relations=tuple(args.allow_relation),
            max_sample_rows=args.max_sample_rows,
            timeout_seconds=args.timeout_seconds,
            redacted_columns=tuple(args.redact_column),
        ),
    )
    build_fastmcp(host).run(transport="stdio")


if __name__ == "__main__":
    main()
