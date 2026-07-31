"""A notification's own lifecycle is UNREAD/READ/CLOSED, not a delivery state.

Before this, `Notification.status` held PENDING/DELIVERED/FAILED, which describes
whether a channel accepted the message. That made "has the recipient dealt with
this?" unanswerable, and it meant one successful DingTalk send could overwrite
the recipient's own reading history. Channel outcomes stay in `Delivery`.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import migrations

from apps.identity.models.user import User
from apps.notifications.models import (
    Delivery,
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationCategory,
    NotificationLevel,
    NotificationStatus,
    Todo,
    TodoStatus,
)

lifecycle_migration = importlib.import_module(
    "apps.notifications.migrations.0002_in_app_notification_lifecycle"
)

pytestmark = pytest.mark.django_db


def build_notification(user: User, todo: Todo, **overrides: object) -> Notification:
    defaults: dict[str, object] = {
        "organization": user.organization,
        "recipient": user,
        "template_code": "todo.created",
        "category": NotificationCategory.ACTION_REQUIRED,
        "level": NotificationLevel.IMPORTANT,
        "summary": todo.title,
        "object_type": todo.source_type,
        "object_id": todo.source_id,
        "dedup_key": f"notify:{todo.dedup_key}",
        "deep_link": todo.deep_link,
        "todo": todo,
    }
    return Notification.objects.create(**{**defaults, **overrides})


def test_a_notification_starts_unread_with_no_lifecycle_timestamps(active_user, todo) -> None:
    notification = build_notification(active_user, todo)

    assert notification.status == NotificationStatus.UNREAD
    assert notification.read_at is None
    assert notification.closed_at is None
    assert notification.close_reason == ""


def test_the_lifecycle_states_are_exactly_unread_read_and_closed() -> None:
    assert set(NotificationStatus.values) == {"UNREAD", "READ", "CLOSED"}


def test_a_notification_carries_its_category_and_level(active_user, todo) -> None:
    notification = build_notification(
        active_user,
        todo,
        category=NotificationCategory.DEADLINE,
        level=NotificationLevel.URGENT,
    )

    assert notification.category == NotificationCategory.DEADLINE
    assert notification.level == NotificationLevel.URGENT


def test_the_six_categories_and_three_levels_are_declared() -> None:
    assert set(NotificationCategory.values) == {
        "ACTION_REQUIRED",
        "DEADLINE",
        "BUSINESS_ALERT",
        "PROCESS_RESULT",
        "SYSTEM_FAILURE",
        "INFORMATION",
    }
    assert set(NotificationLevel.values) == {"URGENT", "IMPORTANT", "NORMAL"}


def test_a_delivered_notification_does_not_migrate_to_read(active_user, todo) -> None:
    """A channel accepted it; nobody read it. The migration must not claim otherwise."""

    notification = build_notification(active_user, todo)
    Notification.objects.filter(pk=notification.pk).update(status="DELIVERED")
    Delivery.objects.create(
        notification=notification,
        channel=DeliveryChannel.IN_APP,
        status=DeliveryStatus.SENT,
    )

    lifecycle_migration.reset_notification_lifecycle(django_apps, None)

    notification.refresh_from_db()
    assert notification.status == NotificationStatus.UNREAD
    assert notification.read_at is None


def test_the_migration_refuses_duplicate_open_todos_instead_of_choosing_a_survivor(
    active_user,
) -> None:
    """Before the sentinel existed MySQL allowed duplicates; discarding one is not ours to do."""

    for _ in range(2):
        Todo.objects.create(
            organization=active_user.organization,
            assignee=active_user,
            todo_type="review",
            source_type="identity.user",
            source_id=active_user.public_id,
            action_code="identity.user.review",
            status=TodoStatus.OPEN,
            dedup_key="review:collision",
            deep_link="/users/x",
            title="Review user status change",
            open_slot=None,
        )

    with pytest.raises(RuntimeError) as excinfo:
        lifecycle_migration.refuse_duplicate_open_todos(django_apps, None)

    assert "review:collision" in str(excinfo.value)
    assert Todo.objects.filter(dedup_key="review:collision").count() == 2


def test_the_migration_occupies_the_sentinel_only_for_open_todos(active_user) -> None:
    def legacy_todo(dedup_key: str, status: str) -> Todo:
        return Todo.objects.create(
            organization=active_user.organization,
            assignee=active_user,
            todo_type="review",
            source_type="identity.user",
            source_id=active_user.public_id,
            action_code="identity.user.review",
            status=status,
            dedup_key=dedup_key,
            deep_link="/users/x",
            title="Review user status change",
            open_slot=None,
        )

    still_open = legacy_todo("review:open", TodoStatus.OPEN)
    settled = legacy_todo("review:done", TodoStatus.COMPLETED)

    lifecycle_migration.occupy_open_todo_sentinel(django_apps, None)

    still_open.refresh_from_db()
    settled.refresh_from_db()
    assert still_open.open_slot == 1
    assert settled.open_slot is None


def test_the_duplicate_guard_runs_before_the_migration_touches_the_schema() -> None:
    """MySQL cannot roll back applied DDL, so the stop-the-line check goes first."""

    operations = lifecycle_migration.Migration.operations
    guard_index = next(
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.RunPython)
        and operation.code is lifecycle_migration.refuse_duplicate_open_todos
    )
    first_schema_index = next(
        index
        for index, operation in enumerate(operations)
        if not isinstance(operation, migrations.RunPython)
    )

    assert guard_index < first_schema_index
