from __future__ import annotations

import json
from pathlib import Path

from evaluator import TARGETS, evaluate_case, summarize


def test_eval_rejects_unsupported_confirmed_claim_and_missing_evidence() -> None:
    case = {
        "id": "missing-keys",
        "expected_root_cause": "missing_keys",
        "required_tools": ["compare_key_coverage"],
        "optional_tools": ["inspect_relations"],
        "forbidden_tools": ["run_sql"],
    }
    transcript = {
        "tool_calls": [],
        "report": {
            "root_cause": "missing_keys",
            "confidence": "confirmed",
            "evidence": [],
        },
        "latency_ms": 5,
        "token_usage": 20,
    }

    result = evaluate_case(case, transcript)

    assert result["required_tool_recall"] == 0
    assert result["unsupported_confirmed_claims"] == 1
    assert result["passed"] is False


def test_eval_rejects_forbidden_calls_even_when_diagnosis_is_correct() -> None:
    case = {
        "id": "exact-match",
        "expected_root_cause": "exact_match",
        "required_tools": ["diagnose_difference"],
        "optional_tools": [],
        "forbidden_tools": ["run_sql"],
    }
    transcript = {
        "tool_calls": [
            {"name": "diagnose_difference", "result": {"status": "passed"}},
            {"name": "run_sql", "result": {}},
        ],
        "report": {
            "root_cause": "exact_match",
            "confidence": "confirmed",
            "evidence": [{"tool": "diagnose_difference", "finding": "passed"}],
        },
    }

    result = evaluate_case(case, transcript)

    assert result["forbidden_calls"] == 1
    assert result["passed"] is False


def test_all_deterministic_cases_meet_encoded_suite_targets() -> None:
    case_paths = sorted((Path(__file__).parents[1] / "cases").glob("*.json"))
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in case_paths]
    assert {case["id"] for case in cases} == {
        "date-boundary",
        "duplicate-keys",
        "exact-match",
        "join-fanout",
        "missing-keys",
        "numeric-mismatch",
        "scd2-alignment",
    }
    results = []
    for case in cases:
        required_tools = case["required_tools"]
        transcript = {
            "tool_calls": [
                {"name": name, "result": {"finding": case["expected_root_cause"]}}
                for name in required_tools
            ],
            "report": {
                "root_cause": case["expected_root_cause"],
                "confidence": "confirmed",
                "evidence": [
                    {"tool": name, "finding": case["expected_root_cause"]}
                    for name in required_tools
                ],
            },
            "latency_ms": 10,
            "token_usage": 50,
        }
        results.append(evaluate_case(case, transcript))

    metrics = summarize(results)

    assert metrics["root_cause_accuracy"] >= TARGETS["root_cause_accuracy"]
    assert metrics["forbidden_call_rate"] == TARGETS["forbidden_call_rate"]
    assert (
        metrics["unsupported_confirmed_claim_rate"] == TARGETS["unsupported_confirmed_claim_rate"]
    )
    assert metrics["valid_report_rate"] == TARGETS["valid_report_rate"]
    assert metrics["meets_targets"] is True
