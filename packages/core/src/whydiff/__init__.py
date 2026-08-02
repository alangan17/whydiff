"""Public API for WhyDiff's typed contracts and database boundary."""

from whydiff.adapters import (
    AdapterClosedError,
    AdapterError,
    BaseAdapter,
    DuckDBAdapter,
    QueryAudit,
    QueryResult,
    QueryTimeoutError,
    ResultLimitError,
)
from whydiff.engine import WhyDiff, diagnose
from whydiff.models import (
    DiagnosisReport,
    DiagnosticFinding,
    FindingStatus,
    MeasureConfig,
    ReconcileRequest,
    Relation,
    ReportStatus,
)
from whydiff.report import render_console, render_json, render_markdown
from whydiff.sql_safety import MultipleStatementsError, SQLSafetyError, UnsafeStatementError

__all__ = [
    "AdapterClosedError",
    "AdapterError",
    "BaseAdapter",
    "DiagnosisReport",
    "DiagnosticFinding",
    "DuckDBAdapter",
    "FindingStatus",
    "MeasureConfig",
    "MultipleStatementsError",
    "QueryAudit",
    "QueryResult",
    "QueryTimeoutError",
    "ReconcileRequest",
    "Relation",
    "ReportStatus",
    "ResultLimitError",
    "SQLSafetyError",
    "UnsafeStatementError",
    "WhyDiff",
    "diagnose",
    "render_console",
    "render_json",
    "render_markdown",
]
