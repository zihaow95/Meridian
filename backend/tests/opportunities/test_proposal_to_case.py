"""Proposal enters case: locked material, decision roles, approval path."""

from __future__ import annotations

from collections.abc import Callable
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
from apps.opportunities.models import Opportunity, ProposalStatus, ProposalVersionLocked
from apps.opportunities.services.configuration import OPPORTUNITY_RULE_DEFINITION_CODE
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.platform.application.command import CommandContext
from apps.stage_gates.errors import MajorGateRoleNotConfigured
from apps.stage_gates.models import GateResult, StageGateInstance
from apps.stage_gates.services.create_review_cycle import CreateProposalReviewCycle
from apps.stage_gates.services.record_major_decision import RecordMajorGateDecision


def _publish_config(organization: Organization, actor: User) -> None:
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
        name="Proposal rules",
    )
    ConfigurationVersion.objects.create(
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
            "quota_minimums": {"USER": 3},
        },
        created_by=actor,
        published_by=actor,
        published_at=timezone.now(),
    )


def _submitted_opportunity(owner: User) -> Opportunity:
    opportunity = CreateOpportunityDraft(
        context=CommandContext.for_actor(owner),
        title="High protein yogurt",
        public_summary="Breakfast protein yogurt",
        market_analysis="Demand exists in convenience channels.",
        core_selling_points="High protein and low sugar.",
        target_users_needs="Breakfast replacement.",
        suggested_retail_price=Decimal("9.90"),
    ).execute()
    SubmitProposal(
        context=CommandContext.for_actor(owner),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-1",
    ).execute()
    opportunity.refresh_from_db()
    return opportunity


def _open_cycle(decider: User, opportunity: Opportunity) -> StageGateInstance:
    return CreateProposalReviewCycle(
        context=CommandContext.for_actor(decider),
        opportunity_public_id=opportunity.public_id,
    ).execute()


@pytest.fixture
def proposer(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(active_user, "opportunity.submit", "opportunity", role_code="PROPOSER")
    return active_user


@pytest.fixture
def decider(another_active_user: User, grant_action: Callable[..., None]) -> User:
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


@pytest.mark.django_db
def test_review_cycle_locks_proposal_version(
    organization: Organization, proposer: User, decider: User
) -> None:
    _publish_config(organization, proposer)
    opportunity = _submitted_opportunity(proposer)
    _open_cycle(decider, opportunity)

    opportunity.refresh_from_db()
    assert opportunity.proposal_status == ProposalStatus.IN_REVIEW
    locked_version = opportunity.current_version
    locked_version.market_analysis = "tampered after lock"
    with pytest.raises(ProposalVersionLocked):
        locked_version.save()


@pytest.mark.django_db
def test_decision_requires_configured_roles(
    organization: Organization, proposer: User, decider: User
) -> None:
    # No configuration published -> decision roles are not configured.
    opportunity = _submitted_opportunity(proposer)
    stage_gate = _open_cycle(decider, opportunity)
    with pytest.raises(MajorGateRoleNotConfigured):
        RecordMajorGateDecision(
            context=CommandContext.for_actor(decider),
            stage_gate_public_id=stage_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            final_decision=GateResult.APPROVED,
            decision_summary="Approved.",
            idempotency_key="gate-1",
        ).execute()


@pytest.mark.django_db
def test_approved_proposal_enters_case(
    organization: Organization, proposer: User, decider: User
) -> None:
    _publish_config(organization, proposer)
    opportunity = _submitted_opportunity(proposer)
    stage_gate = _open_cycle(decider, opportunity)
    RecordMajorGateDecision(
        context=CommandContext.for_actor(decider),
        stage_gate_public_id=stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Approved.",
        idempotency_key="gate-1",
    ).execute()
    opportunity.refresh_from_db()
    assert opportunity.proposal_status == ProposalStatus.CASE_APPROVED
