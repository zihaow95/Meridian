"""Opportunity domain models."""

from __future__ import annotations

from apps.opportunities.models.assessment import (
    CORE_ASSESSMENT_CATEGORIES,
    RESOLVED_ASSESSMENT_STATUSES,
    AssessmentCategory,
    AssessmentStatus,
    CaseAssessment,
)
from apps.opportunities.models.candidate import (
    CandidateSource,
    CandidateStatus,
    CandidateType,
    ProjectCandidate,
    SourceRole,
)
from apps.opportunities.models.member import (
    InvitationStatus,
    MemberRole,
    OpportunityMember,
)
from apps.opportunities.models.opportunity import (
    InitialType,
    Opportunity,
    ProposalStatus,
    QuotaOwnerType,
)
from apps.opportunities.models.proposal_version import (
    ProposalVersion,
    ProposalVersionLocked,
    ProposalVersionStatus,
)
from apps.opportunities.models.quota import (
    EnforcementMode,
    QuotaCountStatus,
    QuotaLedger,
    SubmissionQuota,
)

__all__ = [
    "CORE_ASSESSMENT_CATEGORIES",
    "RESOLVED_ASSESSMENT_STATUSES",
    "AssessmentCategory",
    "AssessmentStatus",
    "CandidateSource",
    "CandidateStatus",
    "CandidateType",
    "CaseAssessment",
    "EnforcementMode",
    "InitialType",
    "InvitationStatus",
    "MemberRole",
    "Opportunity",
    "OpportunityMember",
    "ProjectCandidate",
    "ProposalStatus",
    "ProposalVersion",
    "ProposalVersionLocked",
    "ProposalVersionStatus",
    "QuotaCountStatus",
    "QuotaLedger",
    "QuotaOwnerType",
    "SourceRole",
    "SubmissionQuota",
]
