from whydiff.adapters import BaseAdapter
from whydiff.models import DiagnosisReport, ReconcileRequest

from .basic import compare_row_counts, compare_schema, inspect_relation
from .dates import inspect_date_boundaries
from .fanout import analyze_grain, detect_fanout
from .keys import compare_key_coverage, detect_duplicate_keys
from .measures import compare_numeric_measures
from .scd2 import inspect_scd2_alignment


def diagnose(adapter: BaseAdapter, request: ReconcileRequest) -> DiagnosisReport:
    from whydiff.engine import diagnose as diagnose_report

    return diagnose_report(adapter, request)


def render_json(report: DiagnosisReport, *, indent: int = 2) -> str:
    from whydiff.report import render_json as render

    return render(report, indent=indent)


def render_markdown(report: DiagnosisReport) -> str:
    from whydiff.report import render_markdown as render

    return render(report)


def render_console(report: DiagnosisReport) -> str:
    from whydiff.report import render_console as render

    return render(report)


__all__ = [
    "compare_key_coverage",
    "compare_numeric_measures",
    "compare_row_counts",
    "compare_schema",
    "detect_duplicate_keys",
    "analyze_grain",
    "detect_fanout",
    "diagnose",
    "inspect_relation",
    "inspect_date_boundaries",
    "inspect_scd2_alignment",
    "render_console",
    "render_json",
    "render_markdown",
]
