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


class ProjectTemplateNotPublished(ApiError):
    code = "PROJECT_TEMPLATE_NOT_PUBLISHED"
    message = "A published project execution template is required."
    status_code = 409


class ProjectTemplateInvalid(ApiError):
    code = "PROJECT_TEMPLATE_INVALID"
    message = "The project execution template failed validation."
    status_code = 409


class InvalidStageHandlingRequest(ApiError):
    code = "INVALID_STAGE_HANDLING_REQUEST"
    message = "The requested stage handling mode is not allowed."
    status_code = 409


class PlanChangeNotAllowed(ApiError):
    code = "PLAN_CHANGE_NOT_ALLOWED"
    message = "The plan change cannot be applied."
    status_code = 409


class MigrationImportFailed(ApiError):
    code = "MIGRATION_IMPORT_FAILED"
    message = "The migration batch could not be imported."
    status_code = 409


class MigrationBaselineNotConfirmed(ApiError):
    code = "MIGRATION_BASELINE_NOT_CONFIRMED"
    message = "The migration baseline has not been confirmed."
    status_code = 409


class MigrationBaselineAlreadyConfirmed(ApiError):
    code = "MIGRATION_BASELINE_ALREADY_CONFIRMED"
    message = "The migration baseline has already been confirmed."
    status_code = 409
