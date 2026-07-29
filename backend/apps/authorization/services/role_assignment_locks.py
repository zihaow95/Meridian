"""Shared lock order for role-assignment management writes."""

from __future__ import annotations

from collections.abc import Iterable

from apps.identity.models.organization import Organization
from apps.identity.models.user import User


def lock_organization_and_users(
    *,
    organization_id: int,
    user_ids: Iterable[int],
) -> tuple[Organization, dict[int, User]]:
    """Lock org first, then users by ascending id; return freshly locked users."""

    organization = Organization.objects.select_for_update().get(pk=organization_id)
    ordered_ids = sorted({int(user_id) for user_id in user_ids})
    locked_users: dict[int, User] = {}
    if ordered_ids:
        locked_users = {
            user.id: user
            for user in User.objects.select_for_update().filter(pk__in=ordered_ids).order_by("id")
        }
    return organization, locked_users
