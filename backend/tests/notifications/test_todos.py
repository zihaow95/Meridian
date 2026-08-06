"""Authoritative todo projection also opens the linked in-app notification."""

from __future__ import annotations

import pytest

from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus
from apps.platform.outbox.consumer import consume_once


@pytest.mark.django_db
def test_duplicate_event_creates_one_open_todo(
    event,
    todo_consumer,
    active_user,
    notification_templates,
    notification_policy,
    grant_action,
) -> None:
    notification_templates()
    notification_policy()
    grant_action(active_user, "identity.user.review", "identity.user")

    consume_once(event=event, consumer_code="todo_projection", handler=todo_consumer)
    consume_once(event=event, consumer_code="todo_projection", handler=todo_consumer)

    assert Todo.objects.filter(assignee=active_user, status=TodoStatus.OPEN).count() == 1
    assert (
        Notification.objects.filter(recipient=active_user, status=NotificationStatus.UNREAD).count()
        == 1
    )


@pytest.mark.django_db
def test_todo_projection_creates_in_app_notification_from_business_event(
    event,
    todo_consumer,
    active_user,
    notification_templates,
    notification_policy,
    grant_action,
) -> None:
    notification_templates()
    notification_policy()
    grant_action(active_user, "identity.user.review", "identity.user")

    consume_once(event=event, consumer_code="todo_projection", handler=todo_consumer)

    notification = Notification.objects.get(recipient=active_user)
    todo = Todo.objects.get(assignee=active_user, status=TodoStatus.OPEN)
    assert notification.todo_id == todo.id
    assert notification.template_code == "todo.created"
    assert notification.status == NotificationStatus.UNREAD
