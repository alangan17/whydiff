from __future__ import annotations

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import inspect_date_boundaries


def _adapter(tmp_path) -> DuckDBAdapter:
    path = tmp_path / "dates.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(event_at timestamp)")
    connection.execute(
        "insert into l values ('2026-01-01 12:00:00'), ('2026-01-02 12:00:00'), "
        "('2026-01-03 12:00:00')"
    )
    connection.execute("create table r(event_at timestamp)")
    connection.execute("insert into r values ('2026-01-01 12:00:00'), ('2026-01-02 12:00:00')")
    connection.close()
    return DuckDBAdapter(database=str(path), read_only=True)


def test_date_boundaries_detect_extraction_cutoff_with_bounded_window(tmp_path) -> None:
    findings = inspect_date_boundaries(
        _adapter(tmp_path),
        "l",
        "r",
        "event_at",
        window_days=1,
        sample_limit=2,
    )
    finding = next(item for item in findings if item.code == "extraction_cutoff")

    assert finding.metadata["classification"] == "hypothesis"
    assert finding.evidence["first_divergent_date"] == "2026-01-03"
    assert finding.evidence["left_max_date"] == "2026-01-03"
    assert finding.evidence["right_max_date"] == "2026-01-02"
    assert finding.execution_metadata["window_days"] == 1
    assert len(finding.evidence["boundary_counts"]) <= 2
    assert "LIMIT $sample_limit" in finding.metadata["sample_sql"]
    assert "$boundary_date" in finding.metadata["sample_sql"]
    assert "$window_days" in finding.metadata["sample_sql"]
    assert "DATE '2026-01-03'" not in finding.metadata["sample_sql"]
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "boundary_date", "type": "str"},
        {"name": "sample_limit", "type": "int"},
        {"name": "window_days", "type": "int"},
    ]


def test_date_boundaries_detect_multi_day_tail_cutoff(tmp_path) -> None:
    path = tmp_path / "multi_day_cutoff.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute(
        "create table l as select date '2026-01-01' + cast(i as integer) as event_at "
        "from range(10) as source(i)"
    )
    connection.execute(
        "create table r as select date '2026-01-01' + cast(i as integer) as event_at "
        "from range(8) as source(i)"
    )
    connection.close()

    (finding,) = inspect_date_boundaries(
        DuckDBAdapter(database=str(path), read_only=True),
        "l",
        "r",
        "event_at",
    )

    assert finding.code == "extraction_cutoff"
    assert finding.evidence["first_divergent_date"] == "2026-01-09"
    assert finding.evidence["left_max_date"] == "2026-01-10"
    assert finding.evidence["right_max_date"] == "2026-01-08"
