"""Phase 5 stable error code contract (TRD 04 §19).

Each operations domain error must be an ``ApiError`` subclass and, when it
surfaces through the DRF exception handler, produce the unified
``{code, message, details, trace_id}`` response shape with its documented
status code.
"""

from __future__ import annotations

import pytest

from apps.operations import errors as ops_errors
from apps.platform.api.errors import ApiError
from apps.platform.api.exception_handler import custom_exception_handler

# TRD 04 §19 stable error codes, plus the two pre-existing operations errors
# that must also present as ApiError when they surface via the API.
EXPECTED_CODES: dict[str, tuple[type[ApiError], int]] = {
    "INGESTION_BATCH_DUPLICATE": (ops_errors.IngestionBatchDuplicate, 409),
    "OPERATING_DATA_STRUCTURE_INVALID": (ops_errors.OperatingDataStructureInvalid, 400),
    "OPERATING_DATA_MAPPING_REQUIRED": (ops_errors.OperatingDataMappingRequired, 400),
    "OPERATING_UNIT_MISMATCH": (ops_errors.OperatingUnitMismatch, 400),
    "MANUAL_VALUE_SCOPE_FORBIDDEN": (ops_errors.ManualValueScopeForbidden, 403),
    "MANUAL_VALUE_ALREADY_ACTIVE": (ops_errors.ManualValueAlreadyActive, 409),
    "METRIC_DATA_INSUFFICIENT": (ops_errors.MetricDataInsufficient, 400),
    "METRIC_DEFINITION_NOT_PUBLISHED": (ops_errors.MetricDefinitionNotPublished, 400),
    "RISK_SIGNAL_ALREADY_PROCESSED": (ops_errors.RiskSignalAlreadyProcessed, 409),
    "OPERATING_ISSUE_ALREADY_LINKED": (ops_errors.OperatingIssueAlreadyLinked, 409),
    "ITERATION_PROPOSAL_ALREADY_CREATED": (ops_errors.IterationProposalAlreadyCreated, 409),
    "RETIREMENT_ALREADY_DECIDED": (ops_errors.RetirementAlreadyDecided, 409),
    "RETIREMENT_EXECUTION_FAILED": (ops_errors.RetirementExecutionFailed, 409),
    # Pre-existing operations errors that must also honor the ApiError contract.
    "INGESTION_WARNINGS_UNCONFIRMED": (ops_errors.UnconfirmedIngestionWarnings, 400),
    "OPERATING_SNAPSHOT_IMMUTABLE": (ops_errors.SnapshotImmutable, 409),
}


@pytest.mark.parametrize(
    ("expected_code", "error_type", "expected_status"),
    [(code, cls, status) for code, (cls, status) in EXPECTED_CODES.items()],
)
def test_operations_error_is_api_error_with_stable_code(
    expected_code: str, error_type: type[ApiError], expected_status: int
) -> None:
    assert issubclass(error_type, ApiError)
    assert error_type.code == expected_code
    assert error_type.status_code == expected_status


@pytest.mark.parametrize(
    ("expected_code", "error_type", "expected_status"),
    [(code, cls, status) for code, (cls, status) in EXPECTED_CODES.items()],
)
def test_operations_error_produces_unified_response_shape(
    expected_code: str, error_type: type[ApiError], expected_status: int
) -> None:
    exc = error_type(details={"probe": "value"})

    response = custom_exception_handler(exc, {})

    assert response is not None
    assert response.status_code == expected_status
    body = response.data
    assert set(body) == {"code", "message", "details", "trace_id"}
    assert body["code"] == expected_code
    assert body["details"] == {"probe": "value"}
    assert body["trace_id"]


def test_all_trd_04_section_19_codes_are_covered() -> None:
    """Every code listed in TRD 04 §19 must map to a defined ApiError subclass."""
    trd_codes = {
        "INGESTION_BATCH_DUPLICATE",
        "OPERATING_DATA_STRUCTURE_INVALID",
        "OPERATING_DATA_MAPPING_REQUIRED",
        "OPERATING_UNIT_MISMATCH",
        "MANUAL_VALUE_SCOPE_FORBIDDEN",
        "MANUAL_VALUE_ALREADY_ACTIVE",
        "METRIC_DATA_INSUFFICIENT",
        "METRIC_DEFINITION_NOT_PUBLISHED",
        "RISK_SIGNAL_ALREADY_PROCESSED",
        "OPERATING_ISSUE_ALREADY_LINKED",
        "ITERATION_PROPOSAL_ALREADY_CREATED",
        "RETIREMENT_SUBMISSION_INCOMPLETE",
        "RETIREMENT_ALREADY_DECIDED",
        "RETIREMENT_EXECUTION_FAILED",
    }
    missing = trd_codes - set(EXPECTED_CODES) - {"RETIREMENT_SUBMISSION_INCOMPLETE"}
    assert missing == set(), f"TRD 04 §19 codes without a covered ApiError: {missing}"
    # RetirementSubmissionIncomplete predates this remediation; assert it separately.
    assert ops_errors.RetirementSubmissionIncomplete.code == "RETIREMENT_SUBMISSION_INCOMPLETE"
    assert issubclass(ops_errors.RetirementSubmissionIncomplete, ApiError)
