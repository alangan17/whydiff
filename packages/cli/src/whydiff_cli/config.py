from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


class ConfigurationError(ValueError):
    """The command configuration is invalid or incomplete."""


@dataclass(frozen=True)
class Measure:
    name: str
    expression: str
    absolute_tolerance: Decimal = Decimal("0")
    relative_tolerance: Decimal = Decimal("0")


@dataclass(frozen=True)
class CommandConfig:
    database: str
    left: str | None = None
    right: str | None = None
    relation: str | None = None
    keys: tuple[str, ...] = ()
    measures: tuple[Measure, ...] = ()
    output_format: str = "console"
    output_path: str | None = None
    sample_limit: int = 100
    timeout_seconds: float | None = 30.0
    null_equals_zero: bool = False
    allowed_relations: tuple[str, ...] = ()
    redacted_columns: tuple[str, ...] = ()
    timestamp_column: str | None = None
    window_days: int = 3
    event_timestamp: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    end_inclusive: bool = False


def _mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be a mapping")
    return value


def load_yaml(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"could not load {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigurationError("configuration root must be a mapping")
    return loaded


def build_config(
    raw: dict[str, Any],
    *,
    database: str | None = None,
    left: str | None = None,
    right: str | None = None,
    relation: str | None = None,
    keys: list[str] | None = None,
    measures: list[str] | None = None,
    output_format: str | None = None,
    sample_limit: int | None = None,
    timestamp_column: str | None = None,
    window_days: int | None = None,
    event_timestamp: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    end_inclusive: bool | None = None,
) -> CommandConfig:
    connection = _mapping(raw.get("connection"), "connection")
    comparison = _mapping(raw.get("comparison"), "comparison")
    output = _mapping(raw.get("output"), "output")
    safety = _mapping(raw.get("safety"), "safety")
    database_value = database or connection.get("database") or connection.get("path")
    if not isinstance(database_value, str) or not database_value:
        raise ConfigurationError("connection.database or --database is required")
    key_values = keys if keys else comparison.get("unique_keys", comparison.get("keys", []))
    if not isinstance(key_values, list) or not all(
        isinstance(key, str) and key for key in key_values
    ):
        raise ConfigurationError("comparison.unique_keys must be a list of names")
    raw_measures: object = (
        measures if measures else raw.get("measures", comparison.get("measures", []))
    )
    if not isinstance(raw_measures, list):
        raise ConfigurationError("measures must be a list")
    parsed_measures: list[Measure] = []
    for item in raw_measures:
        if isinstance(item, str):
            name, separator, expression = item.partition("=")
            expression = expression if separator else name
            name = name.strip()
            expression = expression.strip()
            if not name or not expression:
                raise ConfigurationError("measure name and expression must not be empty")
            parsed_measures.append(Measure(name=name, expression=expression))
            continue
        if not isinstance(item, dict) or not item.get("name") or not item.get("expression"):
            raise ConfigurationError("each measure needs name and expression")
        try:
            absolute_tolerance = Decimal(str(item.get("absolute_tolerance", 0)))
            relative_tolerance = Decimal(str(item.get("relative_tolerance", 0)))
            if (
                not absolute_tolerance.is_finite()
                or not relative_tolerance.is_finite()
                or absolute_tolerance < 0
                or relative_tolerance < 0
            ):
                raise ConfigurationError("measure tolerances must be finite and non-negative")
            parsed_measures.append(
                Measure(
                    name=str(item["name"]),
                    expression=str(item["expression"]),
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                )
            )
        except InvalidOperation as exc:
            raise ConfigurationError("measure tolerances must be numbers") from exc
    actual_limit = sample_limit if sample_limit is not None else raw.get("sample_limit", 100)
    if not isinstance(actual_limit, int) or not 1 <= actual_limit <= 10_000:
        raise ConfigurationError("sample_limit must be between 1 and 10000")
    actual_format = output_format or output.get("format", "console")
    if actual_format not in {"console", "json", "markdown"}:
        raise ConfigurationError("output format must be console, json, or markdown")
    actual_window_days = (
        window_days if window_days is not None else comparison.get("window_days", 3)
    )
    if not isinstance(actual_window_days, int) or not 0 <= actual_window_days <= 366:
        raise ConfigurationError("window_days must be between 0 and 366")
    return CommandConfig(
        database=database_value,
        left=left or comparison.get("left"),
        right=right or comparison.get("right"),
        relation=relation or comparison.get("relation"),
        keys=tuple(key_values),
        measures=tuple(parsed_measures),
        output_format=actual_format,
        output_path=output.get("path"),
        sample_limit=actual_limit,
        timeout_seconds=connection.get("timeout_seconds", raw.get("timeout_seconds", 30)),
        null_equals_zero=bool(comparison.get("null_equals_zero", False)),
        allowed_relations=tuple(safety.get("allowed_relations", ())),
        redacted_columns=tuple(safety.get("redacted_columns", ())),
        timestamp_column=timestamp_column or comparison.get("timestamp_column"),
        window_days=actual_window_days,
        event_timestamp=event_timestamp or comparison.get("event_timestamp"),
        valid_from=valid_from or comparison.get("valid_from"),
        valid_to=valid_to or comparison.get("valid_to"),
        end_inclusive=(
            end_inclusive
            if end_inclusive is not None
            else bool(comparison.get("end_inclusive", False))
        ),
    )
