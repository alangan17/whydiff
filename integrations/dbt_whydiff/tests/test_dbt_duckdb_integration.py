from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import duckdb

PACKAGE = Path(__file__).parents[1]


def _copy_package(tmp_path: Path) -> Path:
    destination = tmp_path / "dbt_whydiff"
    shutil.copytree(
        PACKAGE,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".user.yml", "dbt_packages", "logs", "target"),
    )
    return destination / "integration_tests"


def _dbt(project: Path, *arguments: str, expected_exit: int = 0) -> str:
    executable = shutil.which("dbt")
    assert executable is not None, "dbt-duckdb must be installed in the development environment"
    completed = subprocess.run(
        [
            executable,
            *arguments,
            "--project-dir",
            str(project),
            "--profiles-dir",
            str(project),
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == expected_exit, completed.stdout + completed.stderr
    return completed.stdout + completed.stderr


def test_dbt_duckdb_compiles_executes_and_returns_normalized_failures(tmp_path: Path) -> None:
    project = _copy_package(tmp_path)

    _dbt(project, "deps")
    _dbt(project, "seed", "--full-refresh")
    _dbt(project, "compile")
    output = _dbt(project, "test", "--store-failures", expected_exit=1)

    assert "FAIL 4" in output
    connection = duckdb.connect(str(project / "target" / "whydiff.duckdb"), read_only=True)
    audit_table = connection.execute(
        """
        select table_schema, table_name
        from information_schema.tables
        where table_schema like '%dbt_test__audit'
        order by table_name
        limit 1
        """
    ).fetchone()
    assert audit_table is not None
    schema_name, table_name = audit_table
    rows = connection.execute(
        f'''select finding_code, finding_side, key_values
            from "{schema_name}"."{table_name}"
            order by key_values'''
    ).fetchall()
    connection.close()

    assert rows == [
        ("missing_keys", "left_only", "2"),
        ("missing_keys", "right_only", "3"),
        ("duplicate_keys", "duplicate_key", "4"),
        ("duplicate_keys", "duplicate_key", "5"),
    ]
