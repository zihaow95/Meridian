"""Read and close are recipient-owned, conditional and never reopen a closed fact.

Channel delivery is a different story: a successful send must not look like a
read, and closing a source must not invent a fresh unread notification when the
recipient already closed the previous one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.notifications.models import (
    Notification,
    NotificationStatus,
    Todo,
    TodoStatus,
)
from apps.notifications.services.lifecycle import (
    CloseNotification,
    MarkNotificationRead,
    SynchronizeNotificationForSource,
)
from apps.platform.application.command import CommandContext

pytestmark = pytest.mark.django_db


def test_the_recipient_may_mark_their_own_notification_read(active_user, notification) -> None:
    updated = MarkNotificationRead(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
    ).execute()

    assert updated.status == NotificationStatus.READ
    assert updated.read_at is not None


def test_marking_read_is_idempotent_and_keeps_the_first_timestamp(
    active_user, notification
) -> None:
    first = MarkNotificationRead(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
    ).execute()
    first_read_at = first.read_at

    second = MarkNotificationRead(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
    ).execute()

    assert second.status == NotificationStatus.READ
    assert second.read_at == first_read_at


def test_a_closed_notification_is_not_reopened_by_a_later_read(active_user, notification) -> None:
    CloseNotification(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
        close_reason="DONE",
    ).execute()

    result = MarkNotificationRead(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
    ).execute()

    assert result.status == NotificationStatus.CLOSED
    assert result.read_at is None


def test_only_the_recipient_may_mark_a_notification_read(
    active_user, another_active_user, notification
) -> None:
    from apps.platform.api.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        MarkNotificationRead(
            context=CommandContext.for_actor(another_active_user),
            notification_public_id=notification.public_id,
        ).execute()

    notification.refresh_from_db()
    assert notification.status == NotificationStatus.UNREAD


def test_the_recipient_may_close_their_own_notification(active_user, notification) -> None:
    updated = CloseNotification(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
        close_reason="HANDLED",
    ).execute()

    assert updated.status == NotificationStatus.CLOSED
    assert updated.closed_at is not None
    assert updated.close_reason == "HANDLED"


def test_closing_is_idempotent_and_keeps_the_first_reason(active_user, notification) -> None:
    first = CloseNotification(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
        close_reason="FIRST",
    ).execute()

    second = CloseNotification(
        context=CommandContext.for_actor(active_user),
        notification_public_id=notification.public_id,
        close_reason="SECOND",
    ).execute()

    assert second.closed_at == first.closed_at
    assert second.close_reason == "FIRST"


def test_completing_a_todo_closes_its_linked_notifications(active_user, todo, notification) -> None:
    todo.status = TodoStatus.COMPLETED
    todo.open_slot = None
    todo.save(update_fields=["status", "open_slot", "updated_at"])

    closed = SynchronizeNotificationForSource(
        organization_id=todo.organization_id,
        source_type=todo.source_type,
        source_id=todo.source_id,
        close_reason="SOURCE_COMPLETED",
        actor=active_user,
    ).execute()

    assert closed == 1
    notification.refresh_from_db()
    assert notification.status == NotificationStatus.CLOSED
    assert notification.close_reason == "SOURCE_COMPLETED"


def test_synchronizing_the_same_source_twice_does_not_reopen_a_closed_notification(
    active_user, todo, notification
) -> None:
    SynchronizeNotificationForSource(
        organization_id=todo.organization_id,
        source_type=todo.source_type,
        source_id=todo.source_id,
        close_reason="SOURCE_COMPLETED",
        actor=active_user,
    ).execute()
    first_closed_at = Notification.objects.get(pk=notification.pk).closed_at

    SynchronizeNotificationForSource(
        organization_id=todo.organization_id,
        source_type=todo.source_type,
        source_id=todo.source_id,
        close_reason="SOURCE_COMPLETED_AGAIN",
        actor=active_user,
    ).execute()

    notification.refresh_from_db()
    assert notification.status == NotificationStatus.CLOSED
    assert notification.closed_at == first_closed_at
    assert notification.close_reason == "SOURCE_COMPLETED"


def test_cancelling_a_todo_also_closes_linked_notifications(
    active_user, todo, notification
) -> None:
    from apps.audit.models import AuditEvent
    from apps.notifications.services.todos import SettleOpenTodosForSource

    SettleOpenTodosForSource(
        organization_id=todo.organization_id,
        source_type=todo.source_type,
        source_id=todo.source_id,
        status=TodoStatus.CANCELLED,
        close_reason="SOURCE_CANCELLED",
        actor=active_user,
        trace_id="trace-source-settle",
    ).execute()

    notification.refresh_from_db()
    todo.refresh_from_db()
    assert todo.status == TodoStatus.CANCELLED
    assert todo.open_slot is None
    assert notification.status == NotificationStatus.CLOSED
    assert notification.close_reason == "SOURCE_CANCELLED"
    assert AuditEvent.objects.filter(
        action_code="notification.message.close",
        resource_public_id=todo.source_id,
        actor_user=active_user,
        trace_id="trace-source-settle",
    ).exists()


def test_synchronization_ignores_notifications_for_other_sources(
    active_user, todo, notification
) -> None:
    other = Todo.objects.create(
        organization=active_user.organization,
        assignee=active_user,
        todo_type="review",
        source_type="identity.user",
        source_id=uuid4(),
        action_code="identity.user.review",
        status=TodoStatus.OPEN,
        dedup_key=f"review:{uuid4()}",
        deep_link="/users/other",
        title="Other",
        open_slot=1,
    )

    SynchronizeNotificationForSource(
        organization_id=other.organization_id,
        source_type=other.source_type,
        source_id=other.source_id,
        close_reason="SOURCE_COMPLETED",
        actor=active_user,
    ).execute()

    notification.refresh_from_db()
    assert notification.status == NotificationStatus.UNREAD


@pytest.mark.django_db(transaction=True)
def test_source_sync_close_does_not_overwrite_a_concurrent_manual_close(
    active_user, todo, notification
) -> None:
    """Two DB connections race; the first close reason/time must stick."""

    import threading

    from django.db import close_old_connections, connections

    from apps.notifications.services.lifecycle import CloseNotification

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def manual_close() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            CloseNotification(
                context=CommandContext.for_actor(active_user),
                notification_public_id=notification.public_id,
                close_reason="MANUAL_FIRST",
            ).execute()
        except BaseException as exc:  # noqa: BLE001 - collect either outcome
            errors.append(exc)
        finally:
            connections.close_all()

    def sync_close() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            SynchronizeNotificationForSource(
                organization_id=todo.organization_id,
                source_type=todo.source_type,
                source_id=todo.source_id,
                close_reason="SOURCE_COMPLETED",
                actor=active_user,
                trace_id="trace-race",
            ).execute()
        except BaseException as exc:  # noqa: BLE001 - collect either outcome
            errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=manual_close)
    t2 = threading.Thread(target=sync_close)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == []
    notification.refresh_from_db()
    assert notification.status == NotificationStatus.CLOSED
    assert notification.close_reason in {"MANUAL_FIRST", "SOURCE_COMPLETED"}
    first_closed_at = notification.closed_at
    first_reason = notification.close_reason

    # Loser must not overwrite the winner on a follow-up sync.
    SynchronizeNotificationForSource(
        organization_id=todo.organization_id,
        source_type=todo.source_type,
        source_id=todo.source_id,
        close_reason="SOURCE_RETRY",
        actor=active_user,
        trace_id="trace-race-2",
    ).execute()
    notification.refresh_from_db()
    assert notification.close_reason == first_reason
    assert notification.closed_at == first_closed_at


def test_source_sync_close_requires_an_actor_even_without_open_rows(active_user, todo) -> None:
    with pytest.raises(ValueError, match="actor"):
        SynchronizeNotificationForSource(
            organization_id=todo.organization_id,
            source_type=todo.source_type,
            source_id=todo.source_id,
            close_reason="SOURCE_COMPLETED",
            actor=None,  # type: ignore[arg-type]
        ).execute()
