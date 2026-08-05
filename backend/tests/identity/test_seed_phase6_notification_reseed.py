"""Phase 6 seed must keep exactly one unread fixture per notification category.

Acceptance re-runs read and close the fixtures they use, and a run can also stop
between the two. Whatever a previous run consumed, the next seed has to leave one
UNREAD row per category behind without reopening or duplicating history.
"""

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

pytestmark = pytest.mark.django_db


def _seed_fixtures(organization: Organization, actor: User) -> SeedPhase6Command:
    command = SeedPhase6Command()
    command._publish_notification_catalogs(organization, actor)
    command._ensure_notifications(actor)
    return command


def _unread_categories(actor: User) -> set[str]:
    return set(
        Notification.objects.filter(
            recipient=actor,
            dedup_key__startswith="phase6:notify:",
            status=NotificationStatus.UNREAD,
        ).values_list("category", flat=True)
    )


def test_phase6_notification_seed_creates_fresh_unread_when_prior_keys_are_closed(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "notification.read", "identity.user")
    command = _seed_fixtures(organization, active_user)

    Notification.objects.filter(
        recipient=active_user, dedup_key__startswith="phase6:notify:"
    ).update(status=NotificationStatus.CLOSED, close_reason="E2E_CLOSE")

    command._ensure_notifications(active_user)

    assert _unread_categories(active_user) == {category for category, _ in _CATEGORY_LEVELS}
    for category, level in _CATEGORY_LEVELS:
        assert Notification.objects.filter(
            recipient=active_user,
            dedup_key=f"phase6:notify:{category}:{level}:open",
            status=NotificationStatus.UNREAD,
        ).exists()


def test_phase6_notification_seed_reseeds_after_a_run_stops_between_read_and_close(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    """A READ fixture is already consumed; the next run needs a new UNREAD one."""

    grant_action(active_user, "notification.read", "identity.user")
    command = _seed_fixtures(organization, active_user)

    read_ids = list(
        Notification.objects.filter(
            recipient=active_user, dedup_key__startswith="phase6:notify:"
        ).values_list("id", flat=True)
    )
    Notification.objects.filter(id__in=read_ids).update(status=NotificationStatus.READ)

    command._ensure_notifications(active_user)

    assert _unread_categories(active_user) == {category for category, _ in _CATEGORY_LEVELS}
    # READ rows stay readable as history rather than being reopened.
    assert Notification.objects.filter(
        id__in=read_ids, status=NotificationStatus.READ
    ).count() == len(read_ids)


def test_phase6_notification_seed_retires_duplicate_unread_left_by_older_seeds(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    """An upgraded database can already hold rival unread facts for one category."""

    from apps.notifications.services.notifications import CreateInAppNotification

    grant_action(active_user, "notification.read", "identity.user")
    command = SeedPhase6Command()
    command._publish_notification_catalogs(organization, active_user)

    category, level = _CATEGORY_LEVELS[0]
    base = f"phase6:notify:{category}:{level}"
    legacy_keys = (base, f"{base}:open", f"{base}:open:2")
    for key in legacy_keys:
        CreateInAppNotification(
            recipient=active_user,
            template_code=f"phase6.{category.lower()}",
            variables={"title": f"{category}-{level}"},
            object_type="identity.user",
            object_id=active_user.public_id,
            dedup_key=key,
            deep_link="/todos",
            action_code="notification.read",
        ).execute()

    command._ensure_notifications(active_user)

    rows = list(
        Notification.objects.filter(recipient=active_user, dedup_key__startswith=base).order_by(
            "id"
        )
    )
    assert [row.dedup_key for row in rows] == list(legacy_keys)
    unread = [row for row in rows if row.status == NotificationStatus.UNREAD]
    assert [row.dedup_key for row in unread] == [f"{base}:open:2"]
    retired = [row for row in rows if row.status == NotificationStatus.CLOSED]
    assert len(retired) == 2
    assert all(row.close_reason == "SEED_FIXTURE_SUPERSEDED" for row in retired)
    assert all(row.closed_at is not None for row in retired)


def test_phase6_notification_seed_reuses_the_unread_fixture_instead_of_appending(
    organization: Organization,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    """Repeated seeding must not pile up rival unread facts for one category."""

    grant_action(active_user, "notification.read", "identity.user")
    command = _seed_fixtures(organization, active_user)
    first_pass = set(
        Notification.objects.filter(
            recipient=active_user, dedup_key__startswith="phase6:notify:"
        ).values_list("dedup_key", flat=True)
    )

    for _ in range(3):
        command._ensure_notifications(active_user)

    assert (
        set(
            Notification.objects.filter(
                recipient=active_user, dedup_key__startswith="phase6:notify:"
            ).values_list("dedup_key", flat=True)
        )
        == first_pass
    )
    for category, level in _CATEGORY_LEVELS:
        assert (
            Notification.objects.filter(
                recipient=active_user,
                dedup_key__startswith=f"phase6:notify:{category}:{level}",
                status=NotificationStatus.UNREAD,
            ).count()
            == 1
        )
