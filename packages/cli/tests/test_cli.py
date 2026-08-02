from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner
from whydiff_cli.main import app

runner = CliRunner()


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.duckdb"
    connection = duckdb.connect(str(path))
    connection.sql("create table left_table(id integer, amount decimal(10,2))")
    connection.sql("create table right_table(id integer, amount decimal(10,2))")
    connection.sql("insert into left_table values (1, 10), (2, 20)")
    connection.sql("insert into right_table values (1, 10), (3, 30)")
    connection.close()
    return path


def _advanced_database(tmp_path: Path) -> Path:
    path = tmp_path / "advanced.duckdb"
    connection = duckdb.connect(str(path))
    connection.sql("create table before_join(id integer, amount integer)")
    connection.sql("insert into before_join values (1, 10), (2, 20)")
    connection.sql("create table after_join(id integer, amount integer)")
    connection.sql("insert into after_join values (1, 10), (1, 10), (2, 20)")
    connection.sql("create table left_dates(event_at timestamp)")
    connection.sql("create table right_dates(event_at timestamp)")
    connection.sql("insert into left_dates values ('2026-01-01'), ('2026-01-02')")
    connection.sql("insert into right_dates values ('2026-01-01')")
    connection.sql("create table facts(customer_id integer, event_at timestamp)")
    connection.sql("insert into facts values (1, '2026-01-15')")
    connection.sql(
        "create table dimension(customer_id integer, valid_from timestamp, valid_to timestamp)"
    )
    connection.sql("insert into dimension values (1, '2026-01-01', null)")
    connection.close()
    return path


def test_compare_keys_json_reports_difference_and_exit_one(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "compare-keys",
            "--database",
            str(_database(tmp_path)),
            "--left",
            "left_table",
            "--right",
            "right_table",
            "--key",
            "id",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["summary"] == {"left_only": 1, "matched": 1, "right_only": 1}
    assert payload["samples"]["left_only"] == [{"id": 2}]


def test_invalid_yaml_is_a_configuration_error(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text("comparison: [", encoding="utf-8")

    result = runner.invoke(app, ["diagnose", "--config", str(config)])

    assert result.exit_code == 2
    assert "configuration error" in (result.stdout + result.stderr).lower()


def test_help_contains_a_runnable_example() -> None:
    result = runner.invoke(app, ["diagnose", "--help"])

    assert result.exit_code == 0
    assert "whydiff diagnose --database" in result.stdout


def test_unsafe_measure_expression_is_rejected_with_exit_four(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "compare-measures",
            "--database",
            str(_database(tmp_path)),
            "--left",
            "left_table",
            "--right",
            "right_table",
            "--key",
            "id",
            "--measure",
            "amount=sum(amount)); delete from left_table; select sum(amount",
        ],
    )

    assert result.exit_code == 4
    assert "unsafe operation rejected" in (result.stdout + result.stderr).lower()


def test_matched_and_execution_error_exit_codes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    matched = runner.invoke(
        app,
        [
            "compare-keys",
            "--database",
            str(database),
            "--left",
            "left_table",
            "--right",
            "left_table",
            "--key",
            "id",
        ],
    )
    execution_error = runner.invoke(
        app,
        [
            "compare-keys",
            "--database",
            str(database),
            "--left",
            "missing_table",
            "--right",
            "right_table",
            "--key",
            "id",
        ],
    )

    assert matched.exit_code == 0
    assert execution_error.exit_code == 3
    assert "execution error" in (execution_error.stdout + execution_error.stderr).lower()


@pytest.mark.parametrize("tolerance", ["-0.1", ".inf"])
def test_yaml_rejects_non_finite_or_negative_tolerance(tmp_path: Path, tolerance: str) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "connection:",
                "  database: ignored.duckdb",
                "comparison:",
                "  left: expected",
                "  right: actual",
                "  unique_keys: [id]",
                "measures:",
                "  - name: amount",
                "    expression: sum(amount)",
                f"    absolute_tolerance: {tolerance}",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["diagnose", "--config", str(config)])

    assert result.exit_code == 2
    assert "finite and non-negative" in (result.stdout + result.stderr)


@pytest.mark.parametrize(
    ("command", "extra", "output_format"),
    [
        ("inspect-schema", ["--relation", "left_table"], "markdown"),
        ("detect-duplicates", ["--relation", "left_table", "--key", "id"], "console"),
        (
            "compare-measures",
            [
                "--left",
                "left_table",
                "--right",
                "left_table",
                "--key",
                "id",
                "--measure",
                "amount=sum(amount)",
            ],
            "json",
        ),
        (
            "diagnose",
            [
                "--left",
                "left_table",
                "--right",
                "left_table",
                "--key",
                "id",
            ],
            "markdown",
        ),
    ],
)
def test_commands_and_formats_smoke(
    tmp_path: Path, command: str, extra: list[str], output_format: str
) -> None:
    result = runner.invoke(
        app,
        [command, "--database", str(_database(tmp_path)), *extra, "--format", output_format],
    )

    assert result.exit_code == 0
    if output_format == "json":
        assert json.loads(result.stdout)["status"] == "passed"
    elif output_format == "markdown":
        assert result.stdout.startswith("# WhyDiff")
    else:
        assert result.stdout.startswith("WhyDiff")


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        (
            "detect-fanout",
            [
                "--before",
                "before_join",
                "--after",
                "after_join",
                "--key",
                "id",
                "--measure",
                "amount=sum(amount)",
            ],
        ),
        (
            "inspect-dates",
            [
                "--left",
                "left_dates",
                "--right",
                "right_dates",
                "--timestamp-column",
                "event_at",
            ],
        ),
        (
            "inspect-scd2",
            [
                "--fact",
                "facts",
                "--dimension",
                "dimension",
                "--key",
                "customer_id",
                "--event-timestamp",
                "event_at",
                "--valid-from",
                "valid_from",
                "--valid-to",
                "valid_to",
            ],
        ),
    ],
)
def test_advanced_commands_return_standard_finding_reports(
    tmp_path: Path, command: str, arguments: list[str]
) -> None:
    result = runner.invoke(
        app,
        [
            command,
            "--database",
            str(_advanced_database(tmp_path)),
            *arguments,
            "--format",
            "json",
        ],
    )

    assert result.exit_code in {0, 1}
    payload = json.loads(result.stdout)
    assert payload["status"] in {"passed", "failed"}
    assert payload["findings"]
    assert all(finding["generated_sql"] for finding in payload["findings"])


@pytest.mark.parametrize("measure", ["amount=", "=sum(amount)", "   =sum(amount)"])
def test_direct_measure_requires_non_empty_name_and_expression(
    tmp_path: Path, measure: str
) -> None:
    result = runner.invoke(
        app,
        [
            "compare-measures",
            "--database",
            str(_database(tmp_path)),
            "--left",
            "left_table",
            "--right",
            "right_table",
            "--key",
            "id",
            "--measure",
            measure,
        ],
    )

    assert result.exit_code == 2
    assert "measure name and expression" in (result.stdout + result.stderr).lower()


def test_scd2_yaml_end_inclusive_is_preserved_without_direct_override(tmp_path: Path) -> None:
    config = tmp_path / "scd2.yml"
    config.write_text(
        "\n".join(
            [
                "connection:",
                f"  database: {_advanced_database(tmp_path)}",
                "comparison:",
                "  left: facts",
                "  right: dimension",
                "  unique_keys: [customer_id]",
                "  event_timestamp: event_at",
                "  valid_from: valid_from",
                "  valid_to: valid_to",
                "  end_inclusive: true",
                "output:",
                "  format: json",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect-scd2", "--config", str(config)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert all(finding["evidence"]["end_inclusive"] is True for finding in payload["findings"])


def test_scd2_direct_end_inclusive_flag_works(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "inspect-scd2",
            "--database",
            str(_advanced_database(tmp_path)),
            "--fact",
            "facts",
            "--dimension",
            "dimension",
            "--key",
            "customer_id",
            "--event-timestamp",
            "event_at",
            "--valid-from",
            "valid_from",
            "--valid-to",
            "valid_to",
            "--end-inclusive",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert all(finding["evidence"]["end_inclusive"] is True for finding in payload["findings"])
