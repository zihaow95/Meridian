"""Case leadership appointment and assessment editing rules."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.configuration.models import ConfigurationVersion
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.errors import (
    CaseOwnerNotProductManager,
    DeputyLeaderInvalid,
    DeputyLeaderRequired,
)
from apps.opportunities.models import (
    AssessmentStatus,
    CandidateSource,
    CandidateStatus,
    CaseAssessment,
    InvitationStatus,
    MemberRole,
    Opportunity,
    OpportunityMember,
    ProjectCandidate,
    ProposalStatus,
    QuotaOwnerType,
    SourceRole,
)
from apps.opportunities.models.assessment import CORE_ASSESSMENT_CATEGORIES
from apps.opportunities.services.assign_case_leadership import AssignCaseLeadership
from apps.opportunities.services.update_assessment import UpdateCaseAssessment
from apps.platform.application.command import CommandContext


def _source_opportunity(organization: Organization, owner: User, business_no: str) -> Opportunity:
    return Opportunity.objects.create(
        organization=organization,
        business_no=business_no,
        title="Source proposal",
        public_summary="summary",
        proposal_owner=owner,
        quota_owner_type=QuotaOwnerType.USER,
        quota_owner_id=owner.id,
        proposal_status=ProposalStatus.CASE_APPROVED,
    )


def _candidate_with_source(organization: Organization, source: Opportunity) -> ProjectCandidate:
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no=f"PC-{source.business_no}",
        name="Candidate",
        status=CandidateStatus.AWAITING_ASSIGNMENT,
    )
    CandidateSource.objects.create(
        organization=organization,
        candidate=candidate,
        opportunity=source,
        source_role=SourceRole.PRIMARY,
        is_active=True,
        linked_at=timezone.now(),
        linked_by=source.proposal_owner,
    )
    CaseAssessment.objects.bulk_create(
        [
            CaseAssessment(
                organization=organization,
                candidate=candidate,
                category_code=category,
                status=AssessmentStatus.NOT_STARTED,
            )
            for category in CORE_ASSESSMENT_CATEGORIES
        ]
    )
    return candidate


@pytest.mark.django_db
def test_pm_source_assigns_owner_without_deputy(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    source = _source_opportunity(organization, product_manager, "OPP-PM")
    candidate = _candidate_with_source(organization, source)

    result = AssignCaseLeadership(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        case_owner_public_id=product_manager.public_id,
    ).execute()

    assert result.status == CandidateStatus.ASSESSING
    assert result.case_owner_id == product_manager.id
    assert result.deputy_leader_id is None


@pytest.mark.django_db
def test_case_owner_must_be_product_manager(
    organization: Organization,
    active_user: User,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    source = _source_opportunity(organization, product_manager, "OPP-PM")
    candidate = _candidate_with_source(organization, source)

    with pytest.raises(CaseOwnerNotProductManager):
        AssignCaseLeadership(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            case_owner_public_id=active_user.public_id,
        ).execute()


@pytest.mark.django_db
def test_non_pm_source_requires_deputy(
    organization: Organization,
    active_user: User,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    # active_user is not a product manager, so the source is non-PM.
    source = _source_opportunity(organization, active_user, "OPP-NONPM")
    candidate = _candidate_with_source(organization, source)

    with pytest.raises(DeputyLeaderRequired):
        AssignCaseLeadership(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            case_owner_public_id=product_manager.public_id,
        ).execute()


@pytest.mark.django_db
def test_deputy_must_be_active_member_of_source_team(
    organization: Organization,
    active_user: User,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    source = _source_opportunity(organization, active_user, "OPP-NONPM")
    candidate = _candidate_with_source(organization, source)

    outsider = User.objects.create_user(
        organization=organization,
        display_name="Outsider",
        activated_at=timezone.now(),
    )
    with pytest.raises(DeputyLeaderInvalid):
        AssignCaseLeadership(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            case_owner_public_id=product_manager.public_id,
            deputy_leader_public_id=outsider.public_id,
        ).execute()

    member = User.objects.create_user(
        organization=organization,
        display_name="Team member",
        activated_at=timezone.now(),
    )
    OpportunityMember.objects.create(
        organization=organization,
        opportunity=source,
        user=member,
        member_role=MemberRole.COLLABORATOR,
        invitation_status=InvitationStatus.ACCEPTED,
        active_from=timezone.now(),
    )
    result = AssignCaseLeadership(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        case_owner_public_id=product_manager.public_id,
        deputy_leader_public_id=member.public_id,
    ).execute()
    assert result.deputy_leader_id == member.id


@pytest.mark.django_db
def test_update_assessment_records_status_and_conclusion(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    source = _source_opportunity(organization, product_manager, "OPP-PM")
    candidate = _candidate_with_source(organization, source)
    AssignCaseLeadership(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        case_owner_public_id=product_manager.public_id,
    ).execute()

    assessment = UpdateCaseAssessment(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        category_code="COST",
        conclusion="Unit cost is 4.2 CNY.",
        status=AssessmentStatus.CONFIRMED,
    ).execute()

    assert assessment.status == AssessmentStatus.CONFIRMED
    assert assessment.conclusion == "Unit cost is 4.2 CNY."
