"""Integration tests at the public DuckDB adapter seam."""

from datetime import datetime
from pathlib import Path

import duckdb
import pytest
from whydiff.adapters import AdapterClosedError, DuckDBAdapter
from whydiff.models import Relation
from whydiff.sql_safety import UnsafeStatementError


def _create_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE orders (id INTEGER, amount INTEGER)")
    connection.execute("INSERT INTO orders VALUES (1, 10), (2, 20), (3, 30)")
    connection.close()


def test_adapter_executes_select_and_with_queries_against_temporary_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "warehouse.duckdb"
    _create_database(database)

    with DuckDBAdapter(database) as adapter:
        selected = adapter.execute("SELECT id, amount FROM orders ORDER BY id")
        aggregated = adapter.execute(
            "WITH source_values AS (SELECT amount FROM orders) "
            "SELECT sum(amount) AS total FROM source_values"
        )

    assert selected.columns == ("id", "amount")
    assert selected.rows == ((1, 10), (2, 20), (3, 30))
    assert aggregated.rows == ((60,),)


def test_adapter_quotes_every_identifier_component() -> None:
    with DuckDBAdapter() as adapter:
        assert adapter.quote_identifier('orders"; DROP TABLE users; --') == (
            '"orders""; DROP TABLE users; --"'
        )
        assert (
            adapter.render_relation(Relation(catalog="analytics", schema="staging", name="orders"))
            == '"analytics"."staging"."orders"'
        )


def test_adapter_rejects_unsafe_sql_before_execution() -> None:
    with DuckDBAdapter() as adapter:
        with pytest.raises(UnsafeStatementError):
            adapter.execute("CREATE TABLE secrets (value TEXT)")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM read_text('README.md')",
        "SELECT * FROM read_json_objects('/tmp/data.json')",
        "SELECT * FROM sniff_csv('/tmp/data.csv')",
        "SELECT * FROM parquet_metadata('/tmp/data.parquet')",
        "SELECT * FROM excel_scan('/tmp/data.xlsx')",
        "SELECT * FROM read_csv('/tmp/data.csv')",
        "SELECT * FROM read_parquet('/tmp/data.parquet')",
    ],
)
def test_adapter_rejects_external_table_functions_before_execution(sql: str) -> None:
    with DuckDBAdapter() as adapter:
        with pytest.raises(UnsafeStatementError):
            adapter.execute(sql)


def test_adapter_accepts_deterministic_scalar_and_safe_builtin_table_functions() -> None:
    with DuckDBAdapter() as adapter:
        scalars = adapter.execute(
            "SELECT abs(-2), date_trunc('day', DATE '2026-01-02'), length('safe')"
        )
        series = adapter.execute("SELECT * FROM range(3) ORDER BY range")

    assert scalars.rows == ((2, datetime(2026, 1, 2), 4),)
    assert series.rows == ((0,), (1,), (2,))


def test_result_limit_caps_rows_and_records_truncation() -> None:
    with DuckDBAdapter() as adapter:
        result = adapter.execute("SELECT * FROM range(5) ORDER BY range", max_rows=2)

    assert result.rows == ((0,), (1,))
    assert result.truncated is True
    assert result.audit.rows_returned == 2


def test_audit_metadata_is_sanitized() -> None:
    secret = "do-not-record-this-value"

    with DuckDBAdapter() as adapter:
        result = adapter.execute("SELECT ? AS token", parameters=[secret])

    audit = result.audit.model_dump()
    assert audit["backend"] == "duckdb"
    assert audit["statement_type"] == "SELECT"
    assert len(audit["query_hash"]) == 64
    assert secret not in repr(audit)
    assert "sql" not in audit
    assert "parameters" not in audit
    assert "database" not in audit


def test_closed_adapter_rejects_queries() -> None:
    adapter = DuckDBAdapter()
    adapter.close()

    with pytest.raises(AdapterClosedError):
        adapter.execute("SELECT 1")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_rows": 0}, "max_rows must be greater than zero"),
        ({"timeout_seconds": 0}, "timeout_seconds must be greater than zero"),
    ],
)
def test_query_limits_must_be_positive(kwargs: dict[str, int], message: str) -> None:
    with DuckDBAdapter() as adapter:
        with pytest.raises(ValueError, match=message):
            adapter.execute("SELECT 1", **kwargs)  # type: ignore[arg-type]
