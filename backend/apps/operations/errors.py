"""Operations domain errors for ingestion, snapshots, and issues."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class UnconfirmedIngestionWarnings(Exception):
    """Raised when WARNING rows exist and confirm_warnings was not granted."""

    def __init__(self, message: str = "WARNING rows require confirm_warnings=True.") -> None:
        super().__init__(message)
        self.message = message


class SnapshotImmutable(Exception):
    """Raised when an OperatingDataSnapshot is mutated after create."""

    def __init__(self, message: str = "Operating data snapshot cannot be updated.") -> None:
        super().__init__(message)
        self.message = message


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
