"""Behavioral tests for the public WhyDiff model contracts."""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from whydiff.models import (
    DiagnosisReport,
    DiagnosticFinding,
    FindingStatus,
    MeasureConfig,
    ReconcileRequest,
    Relation,
    ReportStatus,
)


def test_public_models_round_trip_through_json() -> None:
    request = ReconcileRequest(
        left=Relation(catalog="analytics", schema="staging", name="orders"),
        right=Relation(schema="production", name="orders"),
        unique_keys=["order_id"],
        measures=[
            MeasureConfig(
                name="revenue",
                expression="sum(amount)",
                absolute_tolerance=Decimal("0.01"),
                relative_tolerance=Decimal("0.001"),
            )
        ],
        sample_limit=25,
        null_equals_zero=True,
    )

    assert ReconcileRequest.model_validate_json(request.model_dump_json()) == request


def test_duplicate_unique_keys_are_rejected_with_actionable_error() -> None:
    with pytest.raises(
        ValidationError, match="unique_keys contains duplicate identifier 'order_id'"
    ):
        ReconcileRequest(
            left=Relation(name="before"),
            right=Relation(name="after"),
            unique_keys=["order_id", "order_id"],
        )


@pytest.mark.parametrize("field", ["absolute_tolerance", "relative_tolerance"])
def test_negative_tolerances_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} must be greater than or equal to zero"):
        MeasureConfig(name="revenue", expression="sum(amount)", **{field: Decimal("-0.01")})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "must not be empty"),
        ("orders.items", "single identifier"),
        ('orders"; DROP TABLE users', "unsafe characters"),
    ],
)
def test_relation_identifier_components_are_validated(value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Relation(name=value)


@pytest.mark.parametrize("sample_limit", [0, -1, 10_001])
def test_sample_limit_is_bounded(sample_limit: int) -> None:
    with pytest.raises(ValidationError, match="sample_limit"):
        ReconcileRequest(
            left=Relation(name="before"),
            right=Relation(name="after"),
            unique_keys=["id"],
            sample_limit=sample_limit,
        )


def test_report_defaults_are_not_shared_between_instances() -> None:
    first = DiagnosisReport(status=ReportStatus.PASSED)
    second = DiagnosisReport(status=ReportStatus.PASSED)

    first.findings.append(
        DiagnosticFinding(
            code="row_count_mismatch",
            status=FindingStatus.WARNING,
            message="Counts differ",
        )
    )

    assert second.findings == []


def test_finding_evidence_round_trips_without_losing_explicit_contract_fields() -> None:
    finding = DiagnosticFinding(
        code="duplicate_keys",
        status=FindingStatus.FAILURE,
        message="Duplicate keys found",
        generated_sql='SELECT "id", count(*) FROM "orders" GROUP BY 1',
        evidence={"duplicate_groups": 2},
        execution_metadata={"elapsed_ms": 12, "rows_returned": 2},
        metadata={"check": "uniqueness"},
    )

    restored = DiagnosticFinding.model_validate_json(finding.model_dump_json())

    assert restored == finding
    assert restored.evidence == {"duplicate_groups": 2}
