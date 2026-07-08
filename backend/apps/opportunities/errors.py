"""Stable domain error codes for the opportunity workflow.

These subclass the platform ApiError so the unified exception handler renders
them with the correct code and status without per-view mapping.
"""

from __future__ import annotations

from collections.abc import Iterable

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


class CandidateVersionConflict(ApiError):
    code = "CANDIDATE_VERSION_CONFLICT"
    message = "The project candidate was updated by another operation."
    status_code = 409


class CaseOwnerNotProductManager(ApiError):
    code = "CASE_OWNER_NOT_PRODUCT_MANAGER"
    message = "The case owner must be a product manager."
    status_code = 400


class DeputyLeaderRequired(ApiError):
    code = "DEPUTY_LEADER_REQUIRED"
    message = "A deputy leader from the original proposal team is required."
    status_code = 400


class DeputyLeaderInvalid(ApiError):
    code = "DEPUTY_LEADER_INVALID"
    message = "The deputy leader must be an active member of a source proposal team."
    status_code = 400


class CaseLeadershipRolesNotConfigured(ApiError):
    code = "CASE_LEADERSHIP_ROLES_NOT_CONFIGURED"
    message = "The product manager roles for case leadership are not configured."
    status_code = 409


class CandidateNotAssignable(ApiError):
    code = "CANDIDATE_NOT_ASSIGNABLE"
    message = "The project candidate cannot accept leadership assignment now."
    status_code = 409


class CaseAssessmentNotEditable(ApiError):
    code = "CASE_ASSESSMENT_NOT_EDITABLE"
    message = "The case assessment cannot be edited in the current status."
    status_code = 409


class ControlledDeliverableRequired(ApiError):
    code = "CONTROLLED_DELIVERABLE_REQUIRED"
    message = "The deliverable must reference a controlled document version."
    status_code = 400


class ProjectReviewNotSubmittable(ApiError):
    code = "PROJECT_REVIEW_NOT_SUBMITTABLE"
    message = "The project review cannot be submitted in the current status."
    status_code = 409


class CaseAssessmentIncomplete(ApiError):
    code = "CASE_ASSESSMENT_INCOMPLETE"
    message = "Some core case assessments are not resolved."
    status_code = 400

    def __init__(self, *, missing_categories: Iterable[str]) -> None:
        self.missing_categories = list(missing_categories)
        super().__init__(details={"missing_categories": self.missing_categories})


class ProjectReviewInputsMissing(ApiError):
    code = "PROJECT_REVIEW_INPUTS_MISSING"
    message = "Required project review inputs are missing."
    status_code = 400

    def __init__(self, *, missing: Iterable[str]) -> None:
        self.missing = list(missing)
        super().__init__(details={"missing": self.missing})
