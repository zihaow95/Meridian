"""Opportunity and proposal version invariants."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.opportunities.models import (
    Opportunity,
    ProposalVersion,
    ProposalVersionLocked,
    ProposalVersionStatus,
)


@pytest.mark.django_db
def test_locked_proposal_version_cannot_be_changed(
    opportunity: Opportunity, proposal_version: ProposalVersion
) -> None:
    proposal_version.lock_for_review(now=timezone.now())

    proposal_version.market_analysis = "changed"
    with pytest.raises(ProposalVersionLocked):
        proposal_version.save()


@pytest.mark.django_db
def test_lock_for_review_sets_locked_status_and_timestamp(
    proposal_version: ProposalVersion,
) -> None:
    now = timezone.now()
    proposal_version.lock_for_review(now=now)

    proposal_version.refresh_from_db()
    assert proposal_version.version_status == ProposalVersionStatus.LOCKED
    assert proposal_version.locked_at is not None


@pytest.mark.django_db
def test_draft_version_content_can_still_be_edited(
    proposal_version: ProposalVersion,
) -> None:
    proposal_version.version_status = ProposalVersionStatus.DRAFT
    proposal_version.save(update_fields=["version_status", "updated_at"])

    proposal_version.core_selling_points = "Refined selling points"
    proposal_version.save()

    proposal_version.refresh_from_db()
    assert proposal_version.core_selling_points == "Refined selling points"
