"""Public SQL-safety policy tests."""

import pytest
from whydiff.sql_safety import (
    MultipleStatementsError,
    SQLSafetyError,
    UnsafeStatementError,
    validate_read_only_sql,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, amount FROM orders WHERE amount > 0",
        "WITH totals AS (SELECT sum(amount) AS amount FROM orders) SELECT * FROM totals",
        "SELECT 1 UNION ALL SELECT 2",
        "-- a harmless comment with a ;\nSELECT 1",
    ],
)
def test_read_only_queries_are_accepted(sql: str) -> None:
    parsed = validate_read_only_sql(sql)

    assert parsed is not None


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO target SELECT * FROM source",
        "UPDATE target SET value = 1",
        "DELETE FROM target",
        "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN DELETE",
        "CREATE TABLE target AS SELECT 1",
        "CREATE OR REPLACE VIEW target AS SELECT 1",
        "DROP TABLE target",
        "ALTER TABLE target ADD COLUMN value INTEGER",
        "TRUNCATE TABLE target",
        "COPY target TO '/tmp/export.csv'",
        "VACUUM",
    ],
)
def test_write_and_ddl_statements_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeStatementError):
        validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH '/tmp/other.db' AS other",
        "DETACH other",
        "INSTALL httpfs",
        "LOAD httpfs",
        "PRAGMA enable_profiling",
        "SET memory_limit = '1GB'",
        "RESET memory_limit",
        "USE other",
        "CALL checkpoint()",
        "EXPORT DATABASE '/tmp/export'",
        "IMPORT DATABASE '/tmp/export'",
        "BEGIN TRANSACTION",
        "COMMIT",
        "ROLLBACK",
    ],
)
def test_duckdb_commands_that_change_session_or_external_state_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeStatementError):
        validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv_auto('/tmp/data.csv')",
        "SELECT * FROM read_json('https://example.test/data.json')",
        "SELECT * FROM read_parquet('/tmp/data.parquet')",
        "SELECT * FROM sqlite_scan('/tmp/data.db', 'users')",
        "SELECT * FROM postgres_scan('secret', 'public', 'users')",
        "SELECT * FROM query('DELETE FROM users')",
        "SELECT * FROM glob('/tmp/*')",
    ],
)
def test_external_io_and_dynamic_sql_functions_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeStatementError):
        validate_read_only_sql(sql)


def test_multiple_statements_are_rejected() -> None:
    with pytest.raises(MultipleStatementsError):
        validate_read_only_sql("SELECT 1; DROP TABLE users")


@pytest.mark.parametrize("sql", ["", "  ", ";", "this is not valid SQL"])
def test_empty_or_unparseable_sql_is_rejected_with_typed_error(sql: str) -> None:
    with pytest.raises(SQLSafetyError):
        validate_read_only_sql(sql)
