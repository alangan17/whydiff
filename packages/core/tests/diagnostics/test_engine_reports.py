from __future__ import annotations

from decimal import Decimal

import duckdb
from whydiff import WhyDiff
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import diagnose, render_console, render_json, render_markdown
from whydiff.models import MeasureConfig, ReconcileRequest, Relation


def _request() -> ReconcileRequest:
    return ReconcileRequest(
        left=Relation(name="l"),
        right=Relation(name="r"),
        unique_keys=["id"],
        measures=[
            MeasureConfig(
                name="amount",
                expression="sum(amount)",
                absolute_tolerance=Decimal("0.01"),
            )
        ],
        sample_limit=2,
    )


def _database(tmp_path, right_amount: str = "10.00") -> str:
    path = tmp_path / "engine.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer, amount decimal(12,2))")
    connection.execute("insert into l values (1, 10.00)")
    connection.execute("create table r(id integer, amount decimal(12,2))")
    connection.execute(f"insert into r values (1, {right_amount})")
    connection.close()
    return str(path)


def test_diagnose_exact_match_is_passed_and_deterministic(tmp_path) -> None:
    report = diagnose(DuckDBAdapter(database=_database(tmp_path), read_only=True), _request())

    assert report.status.value == "passed"
    assert all(finding.status.value == "info" for finding in report.findings)
    assert [finding.code for finding in report.findings] == sorted(
        finding.code for finding in report.findings
    )


def test_diagnose_difference_is_schema_valid_and_reported(tmp_path) -> None:
    path = _database(tmp_path, right_amount="12.00")
    report = WhyDiff.duckdb(path, read_only=True).diagnose(_request())

    assert report.status.value == "failed"
    mismatch = next(finding for finding in report.findings if finding.code == "measure_mismatch")
    assert mismatch.generated_sql
    assert mismatch.evidence["affected_rows"] == 1
    assert mismatch.metadata["classification"] == "confirmed"
    assert mismatch.metadata["cause_codes"] == ["numeric_precision"]

    json_output = render_json(report)
    assert '"status": "failed"' in json_output
    assert '"generated_sql"' in json_output
    markdown = render_markdown(report)
    assert markdown.startswith("# WhyDiff diagnosis: FAILED")
    assert "## Confirmed findings" in markdown
    assert "## Hypotheses" in markdown
    assert render_console(report).startswith("WhyDiff: FAILED")


def test_diagnose_classifies_a_missing_relation_as_schema_mismatch(tmp_path) -> None:
    path = tmp_path / "missing_relation.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer, amount decimal(12,2))")
    connection.close()

    report = diagnose(DuckDBAdapter(database=str(path), read_only=True), _request())

    missing = next(finding for finding in report.findings if finding.code == "missing_relation")
    assert missing.metadata["cause_codes"] == ["schema_mismatch"]
    assert missing.metadata["classification"] == "confirmed"


def test_diagnose_classifies_missing_requested_columns_as_schema_mismatch(tmp_path) -> None:
    path = tmp_path / "missing_columns.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer)")
    connection.execute("create table r(id integer)")
    connection.close()
    request = ReconcileRequest(
        left=Relation(name="l"),
        right=Relation(name="r"),
        unique_keys=["missing_id"],
    )

    report = diagnose(DuckDBAdapter(database=str(path), read_only=True), request)

    missing = [finding for finding in report.findings if finding.code == "missing_columns"]
    assert len(missing) == 2
    assert all(finding.metadata["cause_codes"] == ["schema_mismatch"] for finding in missing)


def test_diagnose_classifies_an_invalid_measure_as_unknown(tmp_path) -> None:
    path = tmp_path / "invalid_measure.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer)")
    connection.execute("insert into l values (1)")
    connection.execute("create table r(id integer)")
    connection.execute("insert into r values (1)")
    connection.close()
    request = ReconcileRequest(
        left=Relation(name="l"),
        right=Relation(name="r"),
        unique_keys=["id"],
        measures=[MeasureConfig(name="missing", expression="sum(missing_amount)")],
    )

    report = diagnose(DuckDBAdapter(database=str(path), read_only=True), request)

    invalid = next(finding for finding in report.findings if finding.code == "invalid_measure")
    assert invalid.metadata["cause_codes"] == ["unknown"]
    assert invalid.metadata["classification"] == "confirmed"


def test_diagnose_uses_exact_key_and_duplicate_cause_codes(tmp_path) -> None:
    path = tmp_path / "key_causes.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer)")
    connection.execute("insert into l values (1), (1), (2)")
    connection.execute("create table r(id integer)")
    connection.execute("insert into r values (2), (3)")
    connection.close()
    request = ReconcileRequest(
        left=Relation(name="l"),
        right=Relation(name="r"),
        unique_keys=["id"],
    )

    report = diagnose(DuckDBAdapter(database=str(path), read_only=True), request)

    coverage = next(
        finding for finding in report.findings if finding.code == "key_coverage_mismatch"
    )
    duplicate = next(
        finding for finding in report.findings if finding.code == "duplicate_business_keys"
    )
    assert coverage.metadata["cause_codes"] == ["missing_keys", "additional_keys"]
    assert duplicate.metadata["cause_codes"] == ["duplicate_business_keys"]


def test_diagnose_classifies_null_semantics_separately(tmp_path) -> None:
    path = tmp_path / "null_handling.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer, amount integer)")
    connection.execute("insert into l values (1, NULL)")
    connection.execute("create table r(id integer, amount integer)")
    connection.execute("insert into r values (1, 0)")
    connection.close()

    report = diagnose(DuckDBAdapter(database=str(path), read_only=True), _request())

    nulls = next(finding for finding in report.findings if finding.code == "null_handling")
    assert nulls.metadata["cause_codes"] == ["null_handling"]
    assert nulls.metadata["classification"] == "confirmed"
