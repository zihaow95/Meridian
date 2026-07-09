"""Shared fixtures for opportunity domain tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.opportunities.models import (
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    ProposalVersion,
    ProposalVersionStatus,
    QuotaOwnerType,
)
from apps.opportunities.services.configuration import OPPORTUNITY_RULE_DEFINITION_CODE
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import StageGateInstance
from apps.stage_gates.services.create_review_cycle import CreateProposalReviewCycle


@dataclass
class ReviewCycleBundle:
    stage_gate: StageGateInstance
    subject: Opportunity
    final_decision_actor: User


@pytest.fixture
def review_cycle(
    active_user: User,
    another_active_user: User,
    grant_action: Callable[..., None],
    opportunity_rules: ConfigurationVersion,
) -> ReviewCycleBundle:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(active_user, "opportunity.submit", "opportunity", role_code="PROPOSER")
    grant_action(
        another_active_user,
        "major_gate.management_conclusion.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(
        another_active_user,
        "major_gate.final_decision.record",
        "stage_gate",
        role_code="BOSS",
    )

    opportunity = CreateOpportunityDraft(
        context=CommandContext.for_actor(active_user),
        title="High protein yogurt",
        public_summary="Breakfast protein yogurt",
        market_analysis="Demand exists in convenience channels.",
        core_selling_points="High protein and low sugar.",
        target_users_needs="Breakfast replacement.",
        suggested_retail_price=Decimal("9.90"),
    ).execute()
    SubmitProposal(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-review-cycle",
    ).execute()

    stage_gate = CreateProposalReviewCycle(
        context=CommandContext.for_actor(another_active_user),
        opportunity_public_id=opportunity.public_id,
    ).execute()
    opportunity.refresh_from_db()
    return ReviewCycleBundle(
        stage_gate=stage_gate,
        subject=opportunity,
        final_decision_actor=another_active_user,
    )


@pytest.fixture
def quota_owner(active_user: User) -> User:
    return active_user


@pytest.fixture
def opportunity(organization: Organization, active_user: User) -> Opportunity:
    opp = Opportunity.objects.create(
        organization=organization,
        business_no="OPP-0001",
        title="High protein yogurt",
        public_summary="Breakfast protein yogurt",
        proposal_owner=active_user,
        quota_owner_type=QuotaOwnerType.USER,
        quota_owner_id=active_user.id,
        proposal_status=ProposalStatus.DRAFT,
    )
    return opp


@pytest.fixture
def proposal_version(organization: Organization, opportunity: Opportunity) -> ProposalVersion:
    version = ProposalVersion.objects.create(
        organization=organization,
        opportunity=opportunity,
        version_number=1,
        version_status=ProposalVersionStatus.SUBMITTED,
        market_analysis="Demand exists in convenience channels.",
        core_selling_points="High protein and low sugar.",
        target_users_needs="Breakfast replacement.",
        suggested_retail_price=Decimal("9.90"),
        submitted_at=timezone.now(),
    )
    opportunity.current_version = version
    opportunity.save(update_fields=["current_version", "updated_at"])
    return version


@pytest.fixture
def opportunity_rules(organization: Organization, active_user: User) -> ConfigurationVersion:
    """Publish the opportunity rule configuration used by leadership/review."""

    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
        name="Proposal rules",
    )
    return ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        content_json={
            "member_limit": 8,
            "eligible_proposer_roles": ["PROPOSER"],
            "management_conclusion_roles": ["MANAGEMENT_COMMITTEE"],
            "final_decision_roles": ["BOSS"],
            "product_manager_roles": ["PRODUCT_MANAGER"],
            "case_leadership_roles": ["PRODUCT_DIRECTOR"],
            "quota_enforcement_mode": "WARN",
            "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
        },
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )


@pytest.fixture
def product_manager(organization: Organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Product Manager",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    # Any grant with this role_code marks the user as a product manager.
    grant_action(user, "opportunity.full.read", "opportunity", role_code="PRODUCT_MANAGER")
    return user


@pytest.fixture
def product_director(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        another_active_user,
        "candidate.leadership.assign",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    grant_action(
        another_active_user,
        "candidate.assessment.edit",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    grant_action(
        another_active_user,
        "candidate.submit_review",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    return another_active_user


@pytest.fixture
def boss(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        another_active_user,
        "major_gate.management_conclusion.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(
        another_active_user,
        "major_gate.final_decision.record",
        "stage_gate",
        role_code="BOSS",
    )
    return another_active_user


@pytest.fixture
def approved_candidate(
    organization: Organization,
    product_manager: User,
    product_director: User,
    boss: User,
    opportunity_rules: ConfigurationVersion,
) -> ProjectCandidate:
    from tests.opportunities.factories import build_approval_ready_candidate

    return build_approval_ready_candidate(
        organization=organization,
        product_manager=product_manager,
        product_director=product_director,
        business_no="APPROVE",
    )


@pytest.fixture
def rollback_candidate(
    organization: Organization,
    product_manager: User,
    product_director: User,
    boss: User,
    opportunity_rules: ConfigurationVersion,
) -> ProjectCandidate:
    from tests.opportunities.factories import build_approval_ready_candidate

    return build_approval_ready_candidate(
        organization=organization,
        product_manager=product_manager,
        product_director=product_director,
        business_no="ROLLBACK",
    )
