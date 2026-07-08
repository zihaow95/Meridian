"""Stable domain error codes for the opportunity workflow.

These subclass the platform ApiError so the unified exception handler renders
them with the correct code and status without per-view mapping.
"""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class ProposalSubmitterNotEligible(ApiError):
    code = "PROPOSAL_SUBMITTER_NOT_ELIGIBLE"
    message = "The proposal owner is not eligible to submit."
    status_code = 403


class ProposalRequiredContentMissing(ApiError):
    code = "PROPOSAL_REQUIRED_CONTENT_MISSING"
    message = "The proposal is missing required core content."
    status_code = 400


class ProposalMemberLimitExceeded(ApiError):
    code = "PROPOSAL_MEMBER_LIMIT_EXCEEDED"
    message = "The proposal team member limit has been exceeded."
    status_code = 400


class ProposalVersionConflict(ApiError):
    code = "PROPOSAL_VERSION_CONFLICT"
    message = "The opportunity was updated by another operation."
    status_code = 409


class ProposalAlreadyInReview(ApiError):
    code = "PROPOSAL_ALREADY_IN_REVIEW"
    message = "The proposal has already entered review."
    status_code = 409


class ProposalNotWithdrawable(ApiError):
    code = "PROPOSAL_NOT_WITHDRAWABLE"
    message = "The proposal can no longer be withdrawn by its owner."
    status_code = 409
