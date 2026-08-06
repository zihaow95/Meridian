"""Stable API errors for configuration publication."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class PublicationApprovalMissing(ApiError):
    code = "CONFIGURATION_PUBLICATION_APPROVAL_MISSING"
    message = "Publishing this configuration requires an approved publication request."
    status_code = 409


class PublicationApprovalUnusable(ApiError):
    code = "CONFIGURATION_PUBLICATION_APPROVAL_UNUSABLE"
    message = "The publication approval does not authorize publishing this version."
    status_code = 409


class PublicationReviewerMustDiffer(ApiError):
    code = "CONFIGURATION_PUBLICATION_REVIEWER_MUST_DIFFER"
    message = "A publication request must be reviewed by someone other than its author."
    status_code = 409


class VersionNotPublishable(ApiError):
    code = "CONFIGURATION_VERSION_NOT_PUBLISHABLE"
    message = "The configuration version cannot be published in its current status."
    status_code = 409


class PublicationRequestNotPending(ApiError):
    code = "CONFIGURATION_PUBLICATION_REQUEST_NOT_PENDING"
    message = "The publication request is no longer pending."
    status_code = 409
