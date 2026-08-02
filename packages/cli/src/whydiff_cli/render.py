from __future__ import annotations

import json
from typing import Any


def render(payload: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(payload, indent=2, sort_keys=True, default=str)
    if output_format == "markdown":
        lines = [f"# WhyDiff: {payload.get('status', 'unknown')}", ""]
        if payload.get("message"):
            lines.extend([str(payload["message"]), ""])
        findings = payload.get("findings", [])
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                lines.extend(
                    [
                        f"## {finding.get('code', 'finding')}",
                        "",
                        str(finding.get("message", "")),
                        "",
                        "```json",
                        json.dumps(finding.get("evidence", {}), indent=2, sort_keys=True),
                        "```",
                        "",
                    ]
                )
        summary = payload.get("summary") or payload.get("evidence") or {}
        if summary:
            lines.extend(["## Evidence", ""])
            lines.extend(f"- **{key}**: `{value}`" for key, value in summary.items())
        return "\n".join(lines)
    message = payload.get("message")
    lines = [f"WhyDiff: {payload.get('status', 'unknown')}"]
    if message:
        lines.append(str(message))
    findings = payload.get("findings", [])
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                lines.append(
                    f"[{finding.get('status', 'unknown')}] "
                    f"{finding.get('code', 'finding')}: {finding.get('message', '')}"
                )
    summary = payload.get("summary") or {}
    lines.extend(f"  {key}: {value}" for key, value in summary.items())
    return "\n".join(lines)
