"""Shared fixtures for opportunity domain tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.models import (
    Opportunity,
    ProposalStatus,
    ProposalVersion,
    ProposalVersionStatus,
    QuotaOwnerType,
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
