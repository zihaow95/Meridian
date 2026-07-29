"""Shared lock order for role-assignment management writes."""

from __future__ import annotations

from collections.abc import Iterable

from apps.identity.models.organization import Organization
from apps.identity.models.user import User


def lock_organization_and_users(
    *,
    organization_id: int,
    user_ids: Iterable[int],
) -> Organization:
    """Lock org first, then users by ascending id to avoid deadlocks."""

    organization = Organization.objects.select_for_update().get(pk=organization_id)
    ordered_ids = sorted({int(user_id) for user_id in user_ids})
    if ordered_ids:
        list(User.objects.select_for_update().filter(pk__in=ordered_ids).order_by("id"))
    return organization
