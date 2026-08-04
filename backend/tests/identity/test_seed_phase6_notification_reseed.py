"""Phase 6 seed must keep one open fixture per notification category after re-runs."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.management.commands.seed_phase6_acceptance import (
    _CATEGORY_LEVELS,
)
from apps.identity.management.commands.seed_phase6_acceptance import (
    Command as SeedPhase6Command,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.notifications.models import Notification, NotificationStatus
from apps.notifications.services.notifications import CreateInAppNotification

pytestmark = pytest.mark.django_db


def test_phase6_notification_seed_creates_fresh_unread_when_prior_keys_are_closed(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "notification.read", "identity.user")
    command = SeedPhase6Command()
    command._publish_notification_catalogs(organization, active_user)
    command._ensure_notifications(active_user)

    for category, level in _CATEGORY_LEVELS:
        base = f"phase6:notify:{category}:{level}"
        Notification.objects.filter(recipient=active_user, dedup_key__startswith=base).update(
            status=NotificationStatus.CLOSED, close_reason="E2E_CLOSE"
        )

    command._ensure_notifications(active_user)

    open_by_category = {
        row.category
        for row in Notification.objects.filter(recipient=active_user).exclude(
            status=NotificationStatus.CLOSED
        )
    }
    assert open_by_category == {category for category, _ in _CATEGORY_LEVELS}
    for category, level in _CATEGORY_LEVELS:
        assert Notification.objects.filter(
            recipient=active_user,
            dedup_key=f"phase6:notify:{category}:{level}:open",
            status=NotificationStatus.UNREAD,
        ).exists()


def test_phase6_notification_seed_refreshes_buried_unread_fixtures(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "notification.read", "identity.user")
    command = SeedPhase6Command()
    command._publish_notification_catalogs(organization, active_user)
    command._ensure_notifications(active_user)

    # Bury the original open fixtures under newer unrelated rows.
    for index in range(45):
        CreateInAppNotification(
            recipient=active_user,
            template_code="phase6.action_required",
            variables={"title": f"traffic-{index}"},
            object_type="identity.user",
            object_id=active_user.public_id,
            dedup_key=f"phase6:traffic:{index}",
            deep_link="/todos",
            action_code="notification.read",
            level="URGENT",
        ).execute()

    command._ensure_notifications(active_user)

    recent_ids = set(
        Notification.objects.filter(recipient=active_user)
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[:40]
    )
    for category, level in _CATEGORY_LEVELS:
        open_row = (
            Notification.objects.filter(
                recipient=active_user,
                dedup_key__startswith=f"phase6:notify:{category}:{level}",
            )
            .exclude(status=NotificationStatus.CLOSED)
            .order_by("-id")
            .first()
        )
        assert open_row is not None
        assert open_row.id in recent_ids
