"""Domain errors for project creation."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class ProjectCreationFailed(ApiError):
    code = "PROJECT_CREATION_FAILED"
    message = "The project could not be created."
    status_code = 500


class ProjectCandidateNotApprovable(ApiError):
    code = "PROJECT_CANDIDATE_NOT_APPROVABLE"
    message = "The project candidate is not ready for approval."
    status_code = 409
