"""CreateIterationOpportunityDraftFromSource owns opportunity writes for iterations."""

from __future__ import annotations

import pytest

from apps.identity.models.user import UserStatus
from apps.opportunities.errors import ProposalOwnerNotEligible
from apps.opportunities.models import InitialType, Opportunity, ProposalStatus
from apps.opportunities.services.create_iteration_from_source import (
    CreateIterationOpportunityDraftFromSource,
)
from apps.platform.application.command import CommandContext


@pytest.mark.django_db(transaction=True)
def test_iteration_source_draft_is_iteration_draft_owned_by_designated_owner(
    organization, active_user, another_active_user, grant_action
) -> None:
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    opportunity = CreateIterationOpportunityDraftFromSource(
        context=CommandContext.for_actor(active_user),
        proposal_owner_public_id=another_active_user.public_id,
        title="Iterate yogurt cup",
        public_summary="From operating issue",
        source_snapshot={
            "product_public_id": "p1",
            "phenomenon_summary": "Low production",
            "signals": [{"signal_public_id": "s1"}],
        },
    ).execute()
    assert opportunity.initial_type == InitialType.ITERATION
    assert opportunity.proposal_status == ProposalStatus.DRAFT
    assert opportunity.proposal_owner_id == another_active_user.id
    assert opportunity.current_version is not None
    assert opportunity.current_version.content_snapshot["phenomenon_summary"] == "Low production"
    assert Opportunity.objects.filter(pk=opportunity.pk).count() == 1


@pytest.mark.django_db(transaction=True)
def test_iteration_source_draft_rejects_ineligible_owner(
    organization, active_user, another_active_user
) -> None:
    with pytest.raises(ProposalOwnerNotEligible) as exc:
        CreateIterationOpportunityDraftFromSource(
            context=CommandContext.for_actor(active_user),
            proposal_owner_public_id=another_active_user.public_id,
            title="No rights",
            source_snapshot={},
        ).execute()
    assert exc.value.code == "PROPOSAL_OWNER_NOT_ELIGIBLE"


@pytest.mark.django_db(transaction=True)
def test_iteration_source_draft_rejects_inactive_owner(
    organization, active_user, another_active_user, grant_action
) -> None:
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    another_active_user.status = UserStatus.DISABLED
    another_active_user.save(update_fields=["status"])
    with pytest.raises(ProposalOwnerNotEligible):
        CreateIterationOpportunityDraftFromSource(
            context=CommandContext.for_actor(active_user),
            proposal_owner_public_id=another_active_user.public_id,
            title="Inactive owner",
            source_snapshot={},
        ).execute()
