from __future__ import annotations

import json
from typing import Any

from whydiff.models import DiagnosisReport, DiagnosticFinding


def render_json(report: DiagnosisReport, *, indent: int = 2) -> str:
    """Render the stable public report contract as deterministic JSON."""
    return json.dumps(report.model_dump(mode="json"), indent=indent, sort_keys=True)


def _evidence_json(finding: DiagnosticFinding) -> str:
    return json.dumps(finding.evidence, indent=2, sort_keys=True, default=str)


def render_markdown(report: DiagnosisReport) -> str:
    confirmed = [
        item for item in report.findings if item.metadata.get("classification") == "confirmed"
    ]
    hypotheses = [
        item for item in report.findings if item.metadata.get("classification") != "confirmed"
    ]
    lines = [f"# WhyDiff diagnosis: {report.status.value.upper()}", ""]
    for heading, findings in (("Confirmed findings", confirmed), ("Hypotheses", hypotheses)):
        lines.extend((f"## {heading}", ""))
        if not findings:
            lines.extend(("None.", ""))
            continue
        for item in findings:
            lines.extend(
                (
                    f"### [{item.status.value.upper()}] {item.code}",
                    "",
                    item.message,
                    "",
                    "```json",
                    _evidence_json(item),
                    "```",
                    "",
                )
            )
            if item.generated_sql:
                lines.extend(("```sql", item.generated_sql, "```", ""))
    return "\n".join(lines).rstrip() + "\n"


def render_console(report: DiagnosisReport) -> str:
    lines = [f"WhyDiff: {report.status.value.upper()}"]
    for item in report.findings:
        classification = str(item.metadata.get("classification", "hypothesis"))
        lines.append(
            f"[{item.status.value.upper()}] {item.code} ({classification}): {item.message}"
        )
    return "\n".join(lines)


def report_as_dict(report: DiagnosisReport) -> dict[str, Any]:
    """Return a JSON-compatible report mapping for console and integration callers."""
    return report.model_dump(mode="json")
