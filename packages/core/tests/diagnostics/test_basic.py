from __future__ import annotations

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import compare_row_counts, compare_schema, inspect_relation
from whydiff.models import Relation


def _adapter_with_tables(tmp_path, statements: tuple[str, ...]) -> DuckDBAdapter:
    path = tmp_path / "diagnostics.duckdb"
    connection = duckdb.connect(str(path))
    for statement in statements:
        connection.execute(statement)
    connection.close()
    return DuckDBAdapter(str(path), read_only=True)


def test_inspect_relation_reports_missing_requested_columns(tmp_path) -> None:
    adapter = _adapter_with_tables(
        tmp_path, ("create table left_data (id integer, amount decimal(10, 2))",)
    )

    finding = inspect_relation(
        adapter,
        Relation(name="left_data"),
        requested_columns=("id", "missing_amount"),
    )

    assert finding.code == "missing_columns"
    assert finding.status.value == "failure"
    assert finding.evidence["missing_columns"] == ["missing_amount"]
    assert "information_schema.columns" in finding.generated_sql


def test_inspect_relation_binds_relation_names_in_metadata_query(tmp_path) -> None:
    adapter = _adapter_with_tables(tmp_path, ('create table "odd-name" (id integer)',))

    finding = inspect_relation(adapter, Relation(name="odd-name"))

    assert finding.code == "relation_inspected"
    assert "$relation_table_name" in finding.generated_sql
    assert "odd-name" not in finding.generated_sql
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "relation_table_name", "type": "str"}
    ]


def test_compare_schema_reports_presence_and_lossy_type_mismatches(tmp_path) -> None:
    adapter = _adapter_with_tables(
        tmp_path,
        (
            "create table left_data (id bigint, left_only varchar, amount decimal(18, 2))",
            "create table right_data (id integer, right_only varchar, amount double)",
        ),
    )

    finding = compare_schema(
        adapter,
        Relation(name="left_data"),
        Relation(name="right_data"),
    )

    evidence = finding.evidence
    assert finding.code == "schema_mismatch"
    assert evidence["left_only"] == ["left_only"]
    assert evidence["right_only"] == ["right_only"]
    assert {item["column"] for item in evidence["type_mismatches"]} == {"amount", "id"}
    assert any(item["potentially_lossy"] for item in evidence["type_mismatches"])
    assert adapter.execute(
        finding.generated_sql,
        parameters={"left_table_name": "left_data", "right_table_name": "right_data"},
    ).rows
    assert "left_data" not in repr(finding.execution_metadata)
    assert "right_data" not in repr(finding.execution_metadata)


def test_compare_row_counts_is_a_hypothesis_with_percent_difference(tmp_path) -> None:
    adapter = _adapter_with_tables(
        tmp_path,
        (
            "create table left_data as select * from range(4)",
            "create table right_data as select * from range(2)",
        ),
    )

    finding = compare_row_counts(
        adapter,
        Relation(name="left_data"),
        Relation(name="right_data"),
    )

    assert finding.code == "row_count_mismatch"
    assert finding.status.value == "warning"
    assert finding.metadata["classification"] == "hypothesis"
    assert finding.evidence == {
        "left_count": 4,
        "right_count": 2,
        "absolute_difference": 2,
        "percentage_difference": 50.0,
    }
