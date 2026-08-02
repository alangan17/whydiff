from __future__ import annotations

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import compare_key_coverage, detect_duplicate_keys
from whydiff.models import Relation


def _adapter(tmp_path, statements: tuple[str, ...]) -> DuckDBAdapter:
    path = tmp_path / "keys.duckdb"
    connection = duckdb.connect(str(path))
    for statement in statements:
        connection.execute(statement)
    connection.close()
    return DuckDBAdapter(database=str(path), read_only=True)


def test_key_coverage_is_null_safe_composite_and_distinct(tmp_path) -> None:
    adapter = _adapter(
        tmp_path,
        (
            "create table l(a integer, b varchar)",
            "insert into l values (1, NULL), (1, NULL), (2, 'x')",
            "create table r(a integer, b varchar)",
            "insert into r values (1, NULL), (3, 'x')",
        ),
    )

    finding = compare_key_coverage(
        adapter,
        Relation(name="l"),
        Relation(name="r"),
        ("a", "b"),
        sample_limit=1,
    )

    assert finding.code == "key_coverage_mismatch"
    assert finding.evidence["matched_distinct_keys"] == 1
    assert finding.evidence["left_only_distinct_keys"] == 1
    assert finding.evidence["right_only_distinct_keys"] == 1
    assert finding.evidence["left_physical_rows"] == 3
    assert finding.evidence["left_distinct_keys"] == 2
    assert len(finding.evidence["left_only_sample"]) == 1
    assert "IS NOT DISTINCT FROM" in finding.generated_sql
    assert all("LIMIT $sample_limit" in sql for sql in finding.metadata["sample_sql"])
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "sample_limit", "type": "int"}
    ]


def test_duplicate_detection_reports_groups_rows_excess_and_sample(tmp_path) -> None:
    adapter = _adapter(
        tmp_path,
        (
            "create table data(a integer, b varchar)",
            "insert into data values (1, NULL), (1, NULL), (1, NULL), (2, 'x'), (2, 'x'), (3, 'y')",
        ),
    )

    finding = detect_duplicate_keys(
        adapter,
        Relation(name="data"),
        ("a", "b"),
        side="left",
        sample_limit=1,
    )

    assert finding.code == "duplicate_business_keys"
    assert finding.evidence["duplicate_groups"] == 2
    assert finding.evidence["duplicated_physical_rows"] == 5
    assert finding.evidence["excess_rows"] == 3
    assert finding.evidence["maximum_multiplicity"] == 3
    assert len(finding.evidence["sample"]) == 1
    assert "LIMIT $sample_limit" in finding.metadata["sample_sql"]
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "sample_limit", "type": "int"}
    ]
