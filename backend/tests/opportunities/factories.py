"""Shared opportunity test object builders."""

from __future__ import annotations

from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.models import (
    AssessmentStatus,
    CandidateSource,
    CandidateStatus,
    CaseAssessment,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    QuotaOwnerType,
    SourceRole,
)
from apps.opportunities.models.assessment import CORE_ASSESSMENT_CATEGORIES
from apps.opportunities.services.submit_project_review import SubmitProjectReview
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import StageCode, StageGateInstance, SubjectType


def build_approval_ready_candidate(
    *,
    organization: Organization,
    product_manager: User,
    product_director: User,
    business_no: str,
) -> ProjectCandidate:
    source = Opportunity.objects.create(
        organization=organization,
        business_no=f"OPP-{business_no}",
        title=f"Source {business_no}",
        public_summary="summary",
        proposal_owner=product_manager,
        quota_owner_type=QuotaOwnerType.USER,
        quota_owner_id=product_manager.id,
        proposal_status=ProposalStatus.CASE_APPROVED,
    )
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no=f"PC-{business_no}",
        name=f"Candidate {business_no}",
        status=CandidateStatus.ASSESSING,
        case_owner=product_manager,
        resource_risk_summary="Supply risk is mitigated.",
        proposed_schedule={"launch": "2026Q4"},
    )
    CandidateSource.objects.create(
        organization=organization,
        candidate=candidate,
        opportunity=source,
        source_role=SourceRole.PRIMARY,
        is_active=True,
        linked_at=timezone.now(),
        linked_by=product_manager,
    )
    CaseAssessment.objects.bulk_create(
        [
            CaseAssessment(
                organization=organization,
                candidate=candidate,
                category_code=category,
                status=AssessmentStatus.CONFIRMED,
            )
            for category in CORE_ASSESSMENT_CATEGORIES
        ]
    )
    SubmitProjectReview(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        idempotency_key=f"approve-setup-{business_no}",
    ).execute()
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.IN_PROJECT_REVIEW
    assert StageGateInstance.objects.filter(
        subject_type=SubjectType.PROJECT_CANDIDATE,
        subject_public_id=candidate.public_id,
        stage_code=StageCode.CASE_TO_PROJECT,
    ).exists()
    return candidate
