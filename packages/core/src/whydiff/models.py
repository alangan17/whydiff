"""Stable, database-agnostic public contracts shared by WhyDiff interfaces.

Fields and serialized enum values in this module form a compatibility boundary.
Additive changes should use defaults; removals, renames, and meaning changes require
a major version bump.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, field_validator

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]*$")

if sys.version_info >= (3, 11):
    from enum import StrEnum as _StrEnum
else:

    class _StrEnum(str, Enum):
        """Python 3.10 fallback preserving the public string-enum contract."""

        def __str__(self) -> str:
            return str.__str__(self)

        def __format__(self, format_spec: str) -> str:
            return str.__format__(self, format_spec)


class ContractModel(BaseModel):
    """Common strict configuration for externally serialized contracts."""

    model_config = ConfigDict(
        extra="forbid",
        serialize_by_alias=True,
        use_enum_values=False,
        validate_by_alias=True,
        validate_by_name=True,
    )


class FindingStatus(_StrEnum):
    """Severity of one diagnostic finding."""

    INFO = "info"
    WARNING = "warning"
    FAILURE = "failure"


class ReportStatus(_StrEnum):
    """Overall outcome of a diagnosis report."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class Relation(ContractModel):
    """Database-independent name of a relation.

    Each component is one identifier rather than a pre-qualified SQL fragment. Adapters
    remain responsible for dialect-specific quoting and rendering.
    """

    name: str
    schema_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    catalog: str | None = None

    @property
    def schema(self) -> str | None:  # type: ignore[override]
        """Return the schema component under its serialized public name."""
        return self.schema_name

    @field_validator("name", "schema_name", "catalog")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        """Reject empty, qualified, or control-bearing identifier components."""
        if value is None:
            return None
        if not value:
            raise ValueError("relation identifier must not be empty")
        if "." in value:
            raise ValueError("relation component must be a single identifier, not a qualified name")
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("relation identifier contains unsafe characters")
        return value


class MeasureConfig(ContractModel):
    """A named aggregate expression and its accepted comparison tolerances."""

    name: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    absolute_tolerance: Decimal = Decimal("0")
    relative_tolerance: Decimal = Decimal("0")

    @field_validator("absolute_tolerance", "relative_tolerance")
    @classmethod
    def validate_tolerance(cls, value: Decimal, info: object) -> Decimal:
        """Require finite, non-negative numeric tolerances."""
        field_name = getattr(info, "field_name", "tolerance")
        if not value.is_finite():
            raise ValueError(f"{field_name} must be finite")
        if value < 0:
            raise ValueError(f"{field_name} must be greater than or equal to zero")
        return value


class ReconcileRequest(ContractModel):
    """Inputs for comparing two relations through deterministic diagnostics."""

    left: Relation
    right: Relation
    unique_keys: list[str] = Field(min_length=1)
    measures: list[MeasureConfig] = Field(default_factory=list)
    sample_limit: int = Field(default=100, ge=1, le=10_000)
    null_equals_zero: bool = False

    @field_validator("unique_keys")
    @classmethod
    def validate_unique_keys(cls, values: list[str]) -> list[str]:
        """Require non-empty identifiers with no duplicates."""
        seen: set[str] = set()
        for key in values:
            if not key:
                raise ValueError("unique_keys must contain only non-empty identifiers")
            if not _IDENTIFIER.fullmatch(key):
                raise ValueError(f"unique_keys contains invalid identifier {key!r}")
            if key in seen:
                raise ValueError(f"unique_keys contains duplicate identifier {key!r}")
            seen.add(key)
        return values


class DiagnosticFinding(ContractModel):
    """One evidence-backed observation produced by a deterministic diagnostic."""

    code: str = Field(min_length=1)
    status: FindingStatus
    message: str = Field(min_length=1)
    generated_sql: str | None = None
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    execution_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DiagnosisReport(ContractModel):
    """Serializable collection of diagnostic findings and its overall status."""

    status: ReportStatus
    findings: list[DiagnosticFinding] = Field(default_factory=list)
