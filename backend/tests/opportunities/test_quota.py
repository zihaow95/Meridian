"""Quota ledger counts each opportunity at most once."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.identity.models.user import User
from apps.opportunities.models import (
    Opportunity,
    QuotaCountStatus,
    QuotaLedger,
    QuotaOwnerType,
)


@pytest.mark.django_db
def test_one_opportunity_counts_quota_once(opportunity: Opportunity, quota_owner: User) -> None:
    QuotaLedger.objects.create(
        organization=opportunity.organization,
        opportunity=opportunity,
        quarter="2026Q3",
        owner_type=QuotaOwnerType.USER,
        owner_id=quota_owner.id,
        count_status=QuotaCountStatus.COUNTED,
    )
    with pytest.raises(IntegrityError):
        QuotaLedger.objects.create(
            organization=opportunity.organization,
            opportunity=opportunity,
            quarter="2026Q3",
            owner_type=QuotaOwnerType.USER,
            owner_id=quota_owner.id,
            count_status=QuotaCountStatus.COUNTED,
        )
