"""Proposal submission eligibility, content, quota and idempotency rules."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from apps.identity.models.user import User
from apps.opportunities.errors import (
    ProposalRequiredContentMissing,
    ProposalSubmitterNotEligible,
    ProposalVersionConflict,
)
from apps.opportunities.models import (
    Opportunity,
    ProposalStatus,
    QuotaCountStatus,
    QuotaLedger,
)
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.platform.application.command import CommandContext


@pytest.fixture
def proposer(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(active_user, "opportunity.submit", "opportunity", role_code="PROPOSER")
    return active_user


def _create_full_draft(owner: User, **overrides: object) -> Opportunity:
    kwargs: dict[str, object] = {
        "title": "High protein yogurt",
        "public_summary": "Breakfast protein yogurt",
        "market_analysis": "Demand exists in convenience channels.",
        "core_selling_points": "High protein and low sugar.",
        "target_users_needs": "Breakfast replacement.",
        "suggested_retail_price": Decimal("9.90"),
    }
    kwargs.update(overrides)
    return CreateOpportunityDraft(context=CommandContext.for_actor(owner), **kwargs).execute()


@pytest.mark.django_db
def test_submit_proposal_requires_eligible_owner(
    active_user: User, opportunity: Opportunity
) -> None:
    service = SubmitProposal(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-1",
    )
    with pytest.raises(ProposalSubmitterNotEligible):
        service.execute()
    opportunity.refresh_from_db()
    assert opportunity.proposal_status == ProposalStatus.DRAFT


@pytest.mark.django_db
def test_eligible_owner_submits_and_counts_quota_once(proposer: User) -> None:
    opportunity = _create_full_draft(proposer)
    result = SubmitProposal(
        context=CommandContext.for_actor(proposer),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-1",
    ).execute()
    assert result.proposal_status == ProposalStatus.SUBMITTED
    ledger = QuotaLedger.objects.filter(opportunity=opportunity)
    assert ledger.count() == 1
    assert ledger.first().count_status == QuotaCountStatus.COUNTED


@pytest.mark.django_db
def test_duplicate_submit_is_idempotent(proposer: User) -> None:
    opportunity = _create_full_draft(proposer)
    SubmitProposal(
        context=CommandContext.for_actor(proposer),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-1",
    ).execute()
    opportunity.refresh_from_db()
    SubmitProposal(
        context=CommandContext.for_actor(proposer),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="submit-2",
    ).execute()
    assert QuotaLedger.objects.filter(opportunity=opportunity).count() == 1
    opportunity.refresh_from_db()
    assert opportunity.proposal_status == ProposalStatus.SUBMITTED


@pytest.mark.django_db
def test_submit_requires_core_content(proposer: User) -> None:
    opportunity = _create_full_draft(
        proposer,
        public_summary="",
        market_analysis="",
        suggested_retail_price=None,
    )
    with pytest.raises(ProposalRequiredContentMissing) as exc:
        SubmitProposal(
            context=CommandContext.for_actor(proposer),
            opportunity_public_id=opportunity.public_id,
            version_no=opportunity.version_no,
            idempotency_key="submit-1",
        ).execute()
    assert "market_analysis" in exc.value.details["missing"]
    assert "public_summary" in exc.value.details["missing"]


@pytest.mark.django_db
def test_stale_version_no_is_rejected(proposer: User) -> None:
    opportunity = _create_full_draft(proposer)
    with pytest.raises(ProposalVersionConflict):
        SubmitProposal(
            context=CommandContext.for_actor(proposer),
            opportunity_public_id=opportunity.public_id,
            version_no=opportunity.version_no + 5,
            idempotency_key="submit-1",
        ).execute()
