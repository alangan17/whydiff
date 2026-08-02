from __future__ import annotations

from decimal import Decimal

import duckdb
from whydiff.adapters import DuckDBAdapter
from whydiff.diagnostics import compare_numeric_measures
from whydiff.models import MeasureConfig, Relation


def _adapter(tmp_path) -> DuckDBAdapter:
    path = tmp_path / "measures.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create table l(id integer, amount decimal(12, 2))")
    connection.execute("insert into l values (1, 100), (2, 0), (3, NULL), (4, -10), (5, 10)")
    connection.execute("create table r(id integer, amount decimal(12, 2))")
    connection.execute("insert into r values (1, 100.5), (2, 1), (3, 0), (4, -12), (6, 999)")
    connection.close()
    return DuckDBAdapter(database=str(path), read_only=True)


def test_measure_comparison_separates_tolerance_material_and_null_mismatch(tmp_path) -> None:
    (finding,) = compare_numeric_measures(
        _adapter(tmp_path),
        Relation(name="l"),
        Relation(name="r"),
        ("id",),
        (
            MeasureConfig(
                name="amount",
                expression="sum(amount)",
                absolute_tolerance=Decimal("0.50"),
                relative_tolerance=Decimal("0.01"),
            ),
        ),
        sample_limit=2,
    )

    assert finding.code == "measure_mismatch"
    assert finding.evidence["matched_key_rows"] == 4
    assert finding.evidence["tolerated_rows"] == 1
    assert finding.evidence["outside_tolerance_rows"] == 2
    assert finding.evidence["null_mismatch_rows"] == 1
    assert finding.evidence["affected_rows"] == 3
    assert len(finding.evidence["sample"]) == 2
    assert "$absolute_tolerance" in finding.generated_sql
    assert "$relative_tolerance" in finding.generated_sql
    assert "0.50" not in finding.generated_sql
    assert "0.01" not in finding.generated_sql
    assert "LIMIT $sample_limit" in finding.metadata["sample_sql"]
    assert finding.execution_metadata["bound_parameters"] == [
        {"name": "absolute_tolerance", "type": "Decimal"},
        {"name": "relative_tolerance", "type": "Decimal"},
        {"name": "sample_limit", "type": "int"},
    ]


def test_measure_comparison_can_treat_null_as_zero_explicitly(tmp_path) -> None:
    (finding,) = compare_numeric_measures(
        _adapter(tmp_path),
        "l",
        "r",
        ("id",),
        (MeasureConfig(name="amount", expression="sum(amount)"),),
        null_equals_zero=True,
    )

    assert finding.evidence["null_mismatch_rows"] == 0
    assert finding.evidence["outside_tolerance_rows"] == 3
    assert finding.metadata["null_equals_zero"] is True
