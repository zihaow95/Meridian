"""Create defer pool records for deferred subjects."""

from __future__ import annotations

from uuid import UUID

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.errors import DeferInputMissing
from apps.opportunities.models import DeferRecord


def create_defer_record(
    *,
    organization: Organization,
    subject_type: str,
    subject_public_id: UUID,
    stage_code: str,
    defer_reason: str = "",
    restart_trigger: str = "",
    next_review_quarter: str = "",
    responsible_user: User | None = None,
    last_conclusion: str = "",
) -> DeferRecord:
    if not defer_reason.strip() and not restart_trigger.strip():
        raise DeferInputMissing()
    return DeferRecord.objects.create(
        organization=organization,
        subject_type=subject_type,
        subject_public_id=subject_public_id,
        stage_code=stage_code,
        last_conclusion=last_conclusion,
        defer_reason=defer_reason,
        restart_trigger=restart_trigger,
        responsible_user=responsible_user,
        next_review_quarter=next_review_quarter,
    )
