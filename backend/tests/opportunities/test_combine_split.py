"""Combine and split candidate source flows."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.errors import (
    CandidateSourceNotCaseApproved,
    ProjectReviewNotSubmittable,
)
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
from apps.opportunities.services.combine_candidate_sources import CombineCandidateSources
from apps.opportunities.services.split_project_candidate import SplitProjectCandidate
from apps.opportunities.services.submit_project_review import SubmitProjectReview
from apps.platform.application.command import CommandContext


def _case_approved(organization: Organization, owner: User, business_no: str) -> Opportunity:
    return Opportunity.objects.create(
        organization=organization,
        business_no=business_no,
        title=f"Case {business_no}",
        public_summary="summary",
        proposal_owner=owner,
        quota_owner_type=QuotaOwnerType.USER,
        quota_owner_id=owner.id,
        proposal_status=ProposalStatus.CASE_APPROVED,
    )


@pytest.mark.django_db
def test_combine_adds_sources_without_merging_opportunities(
    organization: Organization,
    active_user: User,
    product_director: User,
    grant_action,
) -> None:
    grant_action(
        product_director, "candidate.combine", "project_candidate", role_code="PRODUCT_DIRECTOR"
    )
    primary = _case_approved(organization, active_user, "OPP-A")
    extra = _case_approved(organization, active_user, "OPP-B")
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no="PC-COMB",
        name="Combined",
        status=CandidateStatus.AWAITING_ASSIGNMENT,
    )
    CandidateSource.objects.create(
        organization=organization,
        candidate=candidate,
        opportunity=primary,
        source_role=SourceRole.PRIMARY,
        is_active=True,
        linked_at=timezone.now(),
        linked_by=active_user,
    )

    result = CombineCandidateSources(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        opportunity_public_ids=[extra.public_id],
    ).execute()

    assert CandidateSource.objects.filter(candidate=result, is_active=True).count() == 2
    assert Opportunity.objects.filter(proposal_status=ProposalStatus.CASE_APPROVED).count() == 2


@pytest.mark.django_db
def test_combine_rejects_non_case_approved_source(
    organization: Organization,
    active_user: User,
    product_director: User,
    grant_action,
) -> None:
    grant_action(
        product_director, "candidate.combine", "project_candidate", role_code="PRODUCT_DIRECTOR"
    )
    primary = _case_approved(organization, active_user, "OPP-A")
    draft = Opportunity.objects.create(
        organization=organization,
        business_no="OPP-DRAFT",
        title="Draft",
        public_summary="summary",
        proposal_owner=active_user,
        quota_owner_type=QuotaOwnerType.USER,
        quota_owner_id=active_user.id,
        proposal_status=ProposalStatus.DRAFT,
    )
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no="PC-COMB",
        name="Combined",
    )
    CandidateSource.objects.create(
        organization=organization,
        candidate=candidate,
        opportunity=primary,
        source_role=SourceRole.PRIMARY,
        is_active=True,
        linked_at=timezone.now(),
        linked_by=active_user,
    )

    with pytest.raises(CandidateSourceNotCaseApproved):
        CombineCandidateSources(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            opportunity_public_ids=[draft.public_id],
        ).execute()


@pytest.mark.django_db
def test_split_creates_independent_candidates(
    organization: Organization,
    active_user: User,
    product_director: User,
    grant_action,
) -> None:
    grant_action(
        product_director, "candidate.split", "project_candidate", role_code="PRODUCT_DIRECTOR"
    )
    source = _case_approved(organization, active_user, "OPP-SPLIT")

    created = SplitProjectCandidate(
        context=CommandContext.for_actor(product_director),
        opportunity_public_id=source.public_id,
        candidate_names=["Variant A", "Variant B"],
    ).execute()

    assert len(created) == 2
    assert all(c.status == CandidateStatus.AWAITING_ASSIGNMENT for c in created)
    assert CaseAssessment.objects.filter(candidate=created[0]).count() == len(
        CORE_ASSESSMENT_CATEGORIES
    )


@pytest.mark.django_db
def test_source_reconfirm_blocks_project_review_submission(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules,
) -> None:
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no="PC-BLOCK",
        name="Blocked",
        status=CandidateStatus.SOURCE_RECONFIRM_REQUIRED,
        case_owner=product_manager,
        resource_risk_summary="Risk noted.",
        proposed_schedule={"launch": "2026Q4"},
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

    with pytest.raises(ProjectReviewNotSubmittable):
        SubmitProjectReview(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            idempotency_key="blocked",
        ).execute()
