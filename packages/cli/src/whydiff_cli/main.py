from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from whydiff.adapters import SQLSafetyError

from .config import ConfigurationError, build_config, load_yaml
from .render import render
from .runtime import run_operation

app = typer.Typer(
    no_args_is_help=True,
    help="Deterministic, read-only diagnostics for two data relations.",
)


def _execute(
    operation: str,
    *,
    config_path: Path | None,
    database: str | None,
    left: str | None,
    right: str | None,
    relation: str | None,
    keys: list[str] | None,
    measures: list[str] | None,
    output_format: str | None,
    sample_limit: int | None,
    timestamp_column: str | None = None,
    window_days: int | None = None,
    event_timestamp: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    end_inclusive: bool | None = None,
) -> None:
    try:
        config = build_config(
            load_yaml(config_path),
            database=database,
            left=left,
            right=right,
            relation=relation,
            keys=keys,
            measures=measures,
            output_format=output_format,
            sample_limit=sample_limit,
            timestamp_column=timestamp_column,
            window_days=window_days,
            event_timestamp=event_timestamp,
            valid_from=valid_from,
            valid_to=valid_to,
            end_inclusive=end_inclusive,
        )
        payload = run_operation(operation, config)
        rendered = render(payload, config.output_format)
        if config.output_path:
            Path(config.output_path).write_text(rendered + "\n", encoding="utf-8")
        typer.echo(rendered)
        status = payload.get("status")
        raise typer.Exit(1 if status in {"failed", "warning", "failure"} else 0)
    except typer.Exit:
        raise
    except ConfigurationError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except Exception as exc:
        if isinstance(exc, SQLSafetyError):
            typer.echo(f"Unsafe operation rejected: {exc}", err=True)
            raise typer.Exit(4) from exc
        typer.echo(f"Execution error: {exc}", err=True)
        raise typer.Exit(3) from exc


ConfigOption = Annotated[Path | None, typer.Option("--config", help="YAML configuration file.")]
DatabaseOption = Annotated[str | None, typer.Option("--database", help="DuckDB path or :memory:.")]
LeftOption = Annotated[str | None, typer.Option("--left", help="Left relation.")]
RightOption = Annotated[str | None, typer.Option("--right", help="Right relation.")]
KeyOption = Annotated[list[str] | None, typer.Option("--key", help="Unique key; repeatable.")]
MeasureOption = Annotated[
    list[str] | None,
    typer.Option("--measure", help="Measure as name=aggregate_expression; repeatable."),
]
FormatOption = Annotated[str | None, typer.Option("--format", help="console, json, or markdown.")]
LimitOption = Annotated[int | None, typer.Option("--sample-limit", min=1, max=10_000)]


@app.command(
    epilog=(
        "Example: whydiff diagnose --database demo.duckdb --left expected --right actual --key id"
    )
)
def diagnose(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    left: LeftOption = None,
    right: RightOption = None,
    key: KeyOption = None,
    measure: MeasureOption = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Run the ordered deterministic diagnosis workflow."""
    _execute(
        "diagnose",
        config_path=config,
        database=database,
        left=left,
        right=right,
        relation=None,
        keys=key,
        measures=measure,
        output_format=output_format,
        sample_limit=sample_limit,
    )


@app.command("compare-keys")
def compare_keys(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    left: LeftOption = None,
    right: RightOption = None,
    key: KeyOption = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Compare unique-key coverage between two relations."""
    _execute(
        "compare-keys",
        config_path=config,
        database=database,
        left=left,
        right=right,
        relation=None,
        keys=key,
        measures=None,
        output_format=output_format,
        sample_limit=sample_limit,
    )


@app.command("compare-measures")
def compare_measures(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    left: LeftOption = None,
    right: RightOption = None,
    key: KeyOption = None,
    measure: MeasureOption = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Compare aggregate measures for shared keys."""
    _execute(
        "compare-measures",
        config_path=config,
        database=database,
        left=left,
        right=right,
        relation=None,
        keys=key,
        measures=measure,
        output_format=output_format,
        sample_limit=sample_limit,
    )


@app.command("inspect-schema")
def inspect_schema(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    relation: Annotated[str | None, typer.Option("--relation")] = None,
    left: LeftOption = None,
    right: RightOption = None,
    output_format: FormatOption = None,
) -> None:
    """Inspect one schema or compare two schemas."""
    _execute(
        "inspect-schema",
        config_path=config,
        database=database,
        left=left,
        right=right,
        relation=relation,
        keys=None,
        measures=None,
        output_format=output_format,
        sample_limit=None,
    )


@app.command("detect-duplicates")
def detect_duplicates(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    relation: Annotated[str | None, typer.Option("--relation")] = None,
    key: KeyOption = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Detect duplicate key groups in one relation."""
    _execute(
        "detect-duplicates",
        config_path=config,
        database=database,
        left=None,
        right=None,
        relation=relation,
        keys=key,
        measures=None,
        output_format=output_format,
        sample_limit=sample_limit,
    )


@app.command("detect-fanout")
def detect_fanout_command(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    before: Annotated[str | None, typer.Option("--before")] = None,
    after: Annotated[str | None, typer.Option("--after")] = None,
    key: KeyOption = None,
    measure: MeasureOption = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Detect row or measure expansion after a join or transformation."""
    _execute(
        "detect-fanout",
        config_path=config,
        database=database,
        left=before,
        right=after,
        relation=None,
        keys=key,
        measures=measure,
        output_format=output_format,
        sample_limit=sample_limit,
    )


@app.command("inspect-dates")
def inspect_dates_command(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    left: LeftOption = None,
    right: RightOption = None,
    timestamp_column: Annotated[str | None, typer.Option("--timestamp-column")] = None,
    window_days: Annotated[int | None, typer.Option("--window-days", min=0, max=366)] = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Inspect deterministic date-boundary differences."""
    _execute(
        "inspect-dates",
        config_path=config,
        database=database,
        left=left,
        right=right,
        relation=None,
        keys=None,
        measures=None,
        output_format=output_format,
        sample_limit=sample_limit,
        timestamp_column=timestamp_column,
        window_days=window_days,
    )


@app.command("inspect-scd2")
def inspect_scd2_command(
    config: ConfigOption = None,
    database: DatabaseOption = None,
    fact: Annotated[str | None, typer.Option("--fact")] = None,
    dimension: Annotated[str | None, typer.Option("--dimension")] = None,
    key: KeyOption = None,
    event_timestamp: Annotated[str | None, typer.Option("--event-timestamp")] = None,
    valid_from: Annotated[str | None, typer.Option("--valid-from")] = None,
    valid_to: Annotated[str | None, typer.Option("--valid-to")] = None,
    end_inclusive: Annotated[bool | None, typer.Option("--end-inclusive")] = None,
    output_format: FormatOption = None,
    sample_limit: LimitOption = None,
) -> None:
    """Inspect fact-to-SCD2 temporal alignment."""
    _execute(
        "inspect-scd2",
        config_path=config,
        database=database,
        left=fact,
        right=dimension,
        relation=None,
        keys=key,
        measures=None,
        output_format=output_format,
        sample_limit=sample_limit,
        event_timestamp=event_timestamp,
        valid_from=valid_from,
        valid_to=valid_to,
        end_inclusive=end_inclusive,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
