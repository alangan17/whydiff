from __future__ import annotations

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import inspect_scd2_alignment


def _adapter(tmp_path, dimension_rows: str, fact_rows: str) -> DuckDBAdapter:
    path = tmp_path / "scd2.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table facts(customer_id integer, event_at timestamp)")
    connection.execute(f"insert into facts values {fact_rows}")
    connection.execute(
        "create table dimension(customer_id integer, valid_from timestamp, valid_to timestamp)"
    )
    connection.execute(f"insert into dimension values {dimension_rows}")
    connection.close()
    return DuckDBAdapter(database=str(path), read_only=True)


def test_scd2_reports_no_match_boundary_and_open_ended_row(tmp_path) -> None:
    findings = inspect_scd2_alignment(
        _adapter(
            tmp_path,
            "(1, '2026-01-01', '2026-02-01'), (1, '2026-03-01', NULL)",
            "(1, '2026-02-01'), (1, '2026-03-15')",
        ),
        "facts",
        "dimension",
        ("customer_id",),
        "event_at",
        "valid_from",
        "valid_to",
        end_inclusive=False,
        sample_limit=2,
    )

    no_match = next(item for item in findings if item.code == "scd2_no_match")
    boundary = next(item for item in findings if item.code == "scd2_boundary_mismatch")
    assert no_match.evidence["no_match_facts"] == 1
    assert boundary.evidence["exact_end_boundary_facts"] == 1
    assert no_match.evidence["open_ended_dimension_rows"] == 1
    assert len(no_match.evidence["sample"]) == 1
    assert "LIMIT $sample_limit" in no_match.metadata["sample_sql"]
    assert "LIMIT $sample_limit" in boundary.metadata["sample_sql"]
    assert no_match.execution_metadata["bound_parameters"] == [
        {"name": "sample_limit", "type": "int"}
    ]


def test_scd2_reports_overlaps_and_multiple_matches_separately(tmp_path) -> None:
    findings = inspect_scd2_alignment(
        _adapter(
            tmp_path,
            "(1, '2026-01-01', '2026-03-01'), (1, '2026-02-01', NULL)",
            "(1, '2026-02-15')",
        ),
        "facts",
        "dimension",
        ("customer_id",),
        "event_at",
        "valid_from",
        "valid_to",
    )

    assert (
        next(item for item in findings if item.code == "scd2_overlapping_ranges").evidence[
            "overlapping_range_pairs"
        ]
        == 1
    )
    assert (
        next(item for item in findings if item.code == "scd2_multiple_match").evidence[
            "multiple_match_facts"
        ]
        == 1
    )
