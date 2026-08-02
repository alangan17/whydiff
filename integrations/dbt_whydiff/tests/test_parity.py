from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import duckdb
from whydiff import DuckDBAdapter, Relation
from whydiff.diagnostics import compare_key_coverage, detect_duplicate_keys

PACKAGE = Path(__file__).parents[1]


def _integer(evidence: dict[str, object], key: str) -> int:
    value = evidence[key]
    assert isinstance(value, int)
    return value


def _sample_keys(evidence: dict[str, object], key: str) -> set[int]:
    sample = evidence[key]
    assert isinstance(sample, list)
    values: set[int] = set()
    for row in sample:
        assert isinstance(row, dict)
        value = row["id"]
        assert isinstance(value, int)
        values.add(value)
    return values


def _load_seed(connection: duckdb.DuckDBPyConnection, name: str) -> None:
    seed = PACKAGE / "integration_tests" / "seeds" / f"{name}.csv"
    with seed.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    connection.execute(f"create table {name}(id integer, amount integer)")
    connection.executemany(
        f"insert into {name} values (?, ?)",
        [(int(row["id"]), int(row["amount"])) for row in rows],
    )


def test_shared_dbt_fixtures_match_python_classifications(tmp_path: Path) -> None:
    database = tmp_path / "parity.duckdb"
    connection = duckdb.connect(str(database))
    _load_seed(connection, "expected")
    _load_seed(connection, "actual")
    connection.close()

    with DuckDBAdapter(database) as adapter:
        coverage = compare_key_coverage(
            adapter, Relation(name="expected"), Relation(name="actual"), ["id"]
        )
        duplicates = detect_duplicate_keys(adapter, Relation(name="expected"), ["id"], side="left")

    expected = json.loads(
        (PACKAGE / "fixtures" / "parity_expected.json").read_text(encoding="utf-8")
    )
    expected_counts = Counter(expected["classifications"].values())
    coverage_evidence: dict[str, object] = dict(coverage.evidence)
    duplicate_evidence: dict[str, object] = dict(duplicates.evidence)
    duplicate_groups = _integer(duplicate_evidence, "duplicate_groups")
    left_only_keys = _sample_keys(coverage_evidence, "left_only_sample")
    duplicate_keys = _sample_keys(duplicate_evidence, "sample")
    one_sided_duplicates = len(left_only_keys & duplicate_keys)
    shared_duplicates = duplicate_groups - one_sided_duplicates
    actual_counts = Counter(
        {
            "left_only": (
                _integer(coverage_evidence, "left_only_distinct_keys") - one_sided_duplicates
            ),
            "right_only": _integer(coverage_evidence, "right_only_distinct_keys"),
            "duplicate_key": duplicate_groups,
            "matched": _integer(coverage_evidence, "matched_distinct_keys") - shared_duplicates,
        }
    )

    assert actual_counts == expected_counts
    assert 5 in left_only_keys & duplicate_keys
