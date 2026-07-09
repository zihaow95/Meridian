"""Read models for proposal submission quotas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.identity.models.user import User
from apps.opportunities.models import QuotaCountStatus, QuotaLedger, QuotaOwnerType
from apps.opportunities.services.configuration import get_opportunity_rule_snapshot
from apps.opportunities.services.submit_proposal import current_quarter


def serialize_current_proposal_quota(user: User, *, as_of: datetime) -> dict[str, Any]:
    quarter = current_quarter(as_of)
    owner_type = QuotaOwnerType.USER
    owner_id = user.id
    snapshot = get_opportunity_rule_snapshot(user.organization, as_of)
    minimum_count = snapshot.quota_minimums.get(owner_type, 0)
    counted_submissions = QuotaLedger.objects.filter(
        organization_id=user.organization_id,
        quarter=quarter,
        owner_type=owner_type,
        owner_id=owner_id,
        count_status=QuotaCountStatus.COUNTED,
    ).count()
    deficit = max(minimum_count - counted_submissions, 0)
    return {
        "quarter": quarter,
        "owner_type": owner_type,
        "owner_public_id": str(user.public_id),
        "counted_submissions": counted_submissions,
        "minimum_count": minimum_count,
        "enforcement_mode": snapshot.quota_enforcement_mode,
        "is_below_minimum": counted_submissions < minimum_count,
        "deficit": deficit,
    }
