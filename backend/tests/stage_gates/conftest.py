"""Fixtures for major stage gate tests."""

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
from apps.identity.models.user import User
from apps.opportunities.models import Opportunity
from apps.opportunities.services.configuration import OPPORTUNITY_RULE_DEFINITION_CODE
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import StageGateInstance
from apps.stage_gates.services.create_review_cycle import CreateProposalReviewCycle


@pytest.fixture
def phase2_rule_config(organization: Organization, active_user: User) -> ConfigurationVersion:
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
            "quota_enforcement_mode": "WARN",
            "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
        },
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )


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
    phase2_rule_config: ConfigurationVersion,
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
