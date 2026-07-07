"""Notification test fixtures."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.user import User
from apps.notifications.consumers import TodoProjectionConsumer
from apps.notifications.models import Notification, Todo, TodoStatus
from apps.notifications.services.notifications import CreateInAppNotification
from apps.platform.outbox.models import OutboxEvent
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@pytest.fixture
def event(active_user: User) -> OutboxEvent:
    source_id = uuid4()
    return register_outbox_event(
        OutboxMessage(
            event_type="todo.requested",
            aggregate_type="identity.user",
            aggregate_id=source_id,
            payload={
                "assignee_id": active_user.id,
                "organization_id": active_user.organization_id,
                "todo_type": "review",
                "source_type": "identity.user",
                "source_id": str(source_id),
                "action_code": "identity.user.review",
                "dedup_key": f"review:{source_id}",
                "deep_link": f"/users/{source_id}",
                "title": "Review user status change",
            },
            occurred_at=timezone.now(),
        )
    )


@pytest.fixture
def todo_consumer() -> TodoProjectionConsumer:
    return TodoProjectionConsumer()


@pytest.fixture
def todo(active_user: User) -> Todo:
    source_id = uuid4()
    return Todo.objects.create(
        organization=active_user.organization,
        assignee=active_user,
        todo_type="review",
        source_type="identity.user",
        source_id=source_id,
        action_code="identity.user.review",
        status=TodoStatus.OPEN,
        dedup_key=f"review:{source_id}",
        deep_link=f"/users/{source_id}",
        title="Review user status change",
    )


@pytest.fixture
def notification(todo: Todo, active_user: User, monkeypatch) -> Notification:
    monkeypatch.setattr(
        "apps.notifications.services.notifications.authorize",
        lambda *args, **kwargs: type("D", (), {"allowed": True})(),
    )
    result = CreateInAppNotification(
        recipient=active_user,
        template_code="todo.created",
        summary=todo.title,
        object_type=todo.source_type,
        object_id=todo.source_id,
        dedup_key=f"notify:{todo.dedup_key}",
        deep_link=todo.deep_link,
        todo=todo,
        action_code="notification.read",
    ).execute()
    assert result is not None
    return result


class FailingGateway:
    def send(self, *, recipient_user_id: int, summary: str, deep_link: str) -> str:
        raise RuntimeError("DINGTALK_UNAVAILABLE")


@pytest.fixture
def failing_gateway() -> FailingGateway:
    return FailingGateway()
