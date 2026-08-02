"""Deterministic scoring for diagnosis-agent transcripts.

This module deliberately evaluates recorded tool calls and reports. It never
invokes an agent or language model, which keeps the suite reproducible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TARGETS = {
    "root_cause_accuracy": 0.90,
    "forbidden_call_rate": 0.0,
    "unsupported_confirmed_claim_rate": 0.0,
    "valid_report_rate": 1.0,
}

_CONFIDENCE = {"confirmed", "likely", "unknown"}


def _valid_report(report: object) -> bool:
    if not isinstance(report, dict):
        return False
    return (
        isinstance(report.get("root_cause"), str)
        and report.get("confidence") in _CONFIDENCE
        and isinstance(report.get("evidence"), list)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("tool"), str)
            and isinstance(item.get("finding"), str)
            for item in report["evidence"]
        )
    )


def evaluate_case(case: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    calls = transcript.get("tool_calls", [])
    call_names = [call.get("name") for call in calls if isinstance(call, dict)]
    required = set(case.get("required_tools", []))
    optional = set(case.get("optional_tools", []))
    forbidden = set(case.get("forbidden_tools", []))
    made = set(call_names)
    report = transcript.get("report")
    valid = _valid_report(report)
    report_data = report if isinstance(report, dict) else {}
    root_cause_correct = bool(
        valid and report_data.get("root_cause") == case.get("expected_root_cause")
    )
    recall = len(required & made) / len(required) if required else 1.0
    forbidden_count = sum(name in forbidden for name in call_names)
    unnecessary_count = sum(name not in required | optional | forbidden for name in call_names)
    unsupported = int(
        bool(
            valid
            and report_data.get("confidence") == "confirmed"
            and not report_data.get("evidence")
        )
    )
    passed = bool(
        valid and root_cause_correct and recall == 1.0 and forbidden_count == 0 and unsupported == 0
    )
    return {
        "case_id": case.get("id"),
        "passed": passed,
        "root_cause_correct": root_cause_correct,
        "required_tool_recall": recall,
        "unnecessary_calls": unnecessary_count,
        "forbidden_calls": forbidden_count,
        "unsupported_confirmed_claims": unsupported,
        "valid_report": valid,
        "latency_ms": transcript.get("latency_ms"),
        "token_usage": transcript.get("token_usage"),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    if not count:
        raise ValueError("at least one result is required")
    metrics = {
        "root_cause_accuracy": sum(r["root_cause_correct"] for r in results) / count,
        "required_tool_recall": sum(r["required_tool_recall"] for r in results) / count,
        "forbidden_call_rate": sum(r["forbidden_calls"] > 0 for r in results) / count,
        "unsupported_confirmed_claim_rate": sum(
            r["unsupported_confirmed_claims"] > 0 for r in results
        )
        / count,
        "valid_report_rate": sum(r["valid_report"] for r in results) / count,
        "unnecessary_calls": sum(r["unnecessary_calls"] for r in results),
    }
    metrics["meets_targets"] = (
        metrics["root_cause_accuracy"] >= TARGETS["root_cause_accuracy"]
        and metrics["forbidden_call_rate"] == TARGETS["forbidden_call_rate"]
        and metrics["unsupported_confirmed_claim_rate"]
        == TARGETS["unsupported_confirmed_claim_rate"]
        and metrics["valid_report_rate"] == TARGETS["valid_report_rate"]
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a deterministic WhyDiff eval transcript")
    parser.add_argument("case", type=Path)
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args()
    result = evaluate_case(
        json.loads(args.case.read_text(encoding="utf-8")),
        json.loads(args.transcript.read_text(encoding="utf-8")),
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
