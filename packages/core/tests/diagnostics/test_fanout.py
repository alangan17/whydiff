from __future__ import annotations

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import analyze_grain, detect_fanout
from whydiff.models import MeasureConfig, Relation


def _adapter(tmp_path) -> DuckDBAdapter:
    path = tmp_path / "fanout.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table before_join(id integer, amount integer)")
    connection.execute("insert into before_join values (1, 10), (2, 5)")
    connection.execute("create table after_join(id integer, amount integer)")
    connection.execute("insert into after_join values (1, 10), (1, 10), (2, 5)")
    connection.close()
    return DuckDBAdapter(database=str(path), read_only=True)


def test_analyze_grain_reports_physical_and_distinct_multiplicity(tmp_path) -> None:
    finding = analyze_grain(_adapter(tmp_path), "after_join", ("id",), side="after")

    assert finding.evidence["physical_rows"] == 3
    assert finding.evidence["distinct_keys"] == 2
    assert finding.evidence["average_multiplicity"] == 1.5
    assert finding.evidence["maximum_multiplicity"] == 2
    assert "LIMIT $sample_limit" in finding.metadata["sample_sql"]
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "sample_limit", "type": "int"}
    ]


def test_detect_fanout_confirms_added_rows_and_measure_inflation(tmp_path) -> None:
    findings = detect_fanout(
        _adapter(tmp_path),
        Relation(name="before_join"),
        Relation(name="after_join"),
        ("id",),
        (MeasureConfig(name="amount", expression="sum(amount)"),),
        sample_limit=2,
    )
    finding = next(item for item in findings if item.code == "join_fanout")

    assert finding.metadata["classification"] == "confirmed"
    assert finding.evidence["pattern"] == "one_to_many"
    assert finding.evidence["affected_keys"] == 1
    assert finding.evidence["added_rows"] == 1
    assert finding.evidence["measure_inflation"]["amount"] == 10.0
    assert len(finding.evidence["sample"]) == 1
    assert "LIMIT $sample_limit" in finding.metadata["sample_sql"]
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "sample_limit", "type": "int"}
    ]
