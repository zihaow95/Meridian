"""Operations domain errors for ingestion, snapshots, and issues.

Stable codes align with docs/trd/04-operations-iteration-retirement-trd.md §19.
"""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class UnconfirmedIngestionWarnings(ApiError):
    """Raised when WARNING rows exist and confirm_warnings was not granted."""

    code = "INGESTION_WARNINGS_UNCONFIRMED"
    message = "WARNING rows require confirm_warnings=True."
    status_code = 400


class SnapshotImmutable(ApiError):
    """Raised when an OperatingDataSnapshot is mutated after create."""

    code = "OPERATING_SNAPSHOT_IMMUTABLE"
    message = "Operating data snapshot cannot be updated."
    status_code = 409


class IssueVersionConflict(ApiError):
    code = "ISSUE_VERSION_CONFLICT"
    message = "The operating issue was updated by another operation."
    status_code = 409


class IssueImmutableState(ApiError):
    code = "ISSUE_IMMUTABLE_STATE"
    message = "The operating issue cannot be changed in its current state."
    status_code = 409


class RetirementSubmissionIncomplete(ApiError):
    code = "RETIREMENT_SUBMISSION_INCOMPLETE"
    message = "The retirement submission is missing required materials or fields."
    status_code = 400


class RetirementNotExecutable(ApiError):
    code = "RETIREMENT_NOT_EXECUTABLE"
    message = "The retirement plan cannot be executed in its current state."
    status_code = 409


class IngestionBatchDuplicate(ApiError):
    code = "INGESTION_BATCH_DUPLICATE"
    message = "An ingestion batch with this source and batch key already completed."
    status_code = 409


class OperatingDataStructureInvalid(ApiError):
    code = "OPERATING_DATA_STRUCTURE_INVALID"
    message = "The operating data has a structural error."
    status_code = 400


class OperatingDataMappingRequired(ApiError):
    code = "OPERATING_DATA_MAPPING_REQUIRED"
    message = "The SKU or channel could not be mapped and requires manual resolution."
    status_code = 400


class OperatingUnitMismatch(ApiError):
    code = "OPERATING_UNIT_MISMATCH"
    message = "The unit or currency is incompatible with the published metric definition."
    status_code = 400


class ManualValueScopeForbidden(ApiError):
    code = "MANUAL_VALUE_SCOPE_FORBIDDEN"
    message = "The actor is not authorized to modify manual values for this product/channel."
    status_code = 403


class ManualValueAlreadyActive(ApiError):
    code = "MANUAL_VALUE_ALREADY_ACTIVE"
    message = "An ACTIVE manual effective value already exists for this key."
    status_code = 409


class MetricDataInsufficient(ApiError):
    code = "METRIC_DATA_INSUFFICIENT"
    message = "Data coverage is insufficient for this metric and period."
    status_code = 400


class MetricDefinitionNotPublished(ApiError):
    code = "METRIC_DEFINITION_NOT_PUBLISHED"
    message = "The metric definition is not published."
    status_code = 400


class RiskSignalAlreadyProcessed(ApiError):
    code = "RISK_SIGNAL_ALREADY_PROCESSED"
    message = "The risk signal status does not allow this operation."
    status_code = 409


class OperatingIssueAlreadyLinked(ApiError):
    code = "OPERATING_ISSUE_ALREADY_LINKED"
    message = "The signal already has an active primary operating issue."
    status_code = 409


class IterationProposalAlreadyCreated(IssueImmutableState):
    """A specialized, stable-coded IssueImmutableState for repeat conversion attempts."""

    code = "ITERATION_PROPOSAL_ALREADY_CREATED"
    message = "The operating issue has already been converted to an iteration proposal."
    status_code = 409


class RetirementAlreadyDecided(ApiError):
    code = "RETIREMENT_ALREADY_DECIDED"
    message = "The PRODUCT_RETIREMENT stage gate has already been decided."
    status_code = 409


class RetirementExecutionFailed(ApiError):
    code = "RETIREMENT_EXECUTION_FAILED"
    message = "The approved retirement plan failed to execute an action."
    status_code = 409
