"""Domain errors for the pilot batch and feedback lifecycle."""

from __future__ import annotations

from apps.platform.api.errors import ApiError, ValidationFailedError


class PilotValidationError(ValidationFailedError):
    code = "PILOT_VALIDATION_FAILED"


class FeedbackVersionConflict(ApiError):
    code = "FEEDBACK_VERSION_CONFLICT"
    message = "The feedback was modified by another request."
    status_code = 409


class BatchCompletionBlocked(ValidationFailedError):
    code = "PILOT_BATCH_COMPLETION_BLOCKED"
    message = "Open P0/P1 feedback blocks batch completion."
