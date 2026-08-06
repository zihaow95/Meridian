"""Notification test fixtures."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import (
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.notifications.consumers import TodoProjectionConsumer
from apps.notifications.models import Notification, Todo, TodoStatus
from apps.notifications.services.notifications import CreateInAppNotification
from apps.platform.outbox.models import OutboxEvent
from apps.platform.outbox.services import OutboxMessage, register_outbox_event

TODO_TEMPLATE = {
    "template_code": "todo.created",
    "category": "ACTION_REQUIRED",
    "default_level": "IMPORTANT",
    "summary_template": "待办 {title} 需要处理",
    "allowed_variables": ["title"],
}
IN_APP_RULES = [
    {"category": "ACTION_REQUIRED", "level": "IMPORTANT", "channels": ["IN_APP"]},
]


def publish_configuration(
    *,
    organization: Organization,
    created_by: User,
    definition_code: str,
    content: dict[str, Any],
) -> ConfigurationVersion:
    """Publish a configuration version the way `PublishVersion` leaves the table."""

    definition, _ = ConfigurationDefinition.objects.get_or_create(
        organization=organization,
        definition_code=definition_code,
        defaults={"name": definition_code, "description": ""},
    )
    ConfigurationVersion.objects.filter(
        definition=definition, status=ConfigurationStatus.PUBLISHED
    ).update(status=ConfigurationStatus.RETIRED, current_published_slot=None)
    return ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=ConfigurationVersion.objects.filter(definition=definition).count() + 1,
        status=ConfigurationStatus.PUBLISHED,
        current_published_slot=1,
        content_json=content,
        created_by=created_by,
        published_at=timezone.now(),
    )


@pytest.fixture
def notification_templates(organization: Organization, active_user: User) -> Any:
    def _apply(entries: list[dict[str, Any]] | None = None) -> ConfigurationVersion:
        return publish_configuration(
            organization=organization,
            created_by=active_user,
            definition_code=NOTIFICATION_TEMPLATE_CATALOG_CODE,
            content={"templates": entries if entries is not None else [TODO_TEMPLATE]},
        )

    return _apply


@pytest.fixture
def notification_policy(organization: Organization, active_user: User) -> Any:
    def _apply(rules: list[dict[str, Any]] | None = None) -> ConfigurationVersion:
        return publish_configuration(
            organization=organization,
            created_by=active_user,
            definition_code=NOTIFICATION_DELIVERY_POLICY_CODE,
            content={"rules": rules if rules is not None else IN_APP_RULES},
        )

    return _apply


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
        open_slot=1,
    )


@pytest.fixture
def allow_notification(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.notifications.services.notifications.authorize",
        lambda *args, **kwargs: type("D", (), {"allowed": True})(),
    )


@pytest.fixture
def notification(
    todo: Todo,
    active_user: User,
    allow_notification: None,
    notification_templates: Any,
    notification_policy: Any,
) -> Notification:
    notification_templates()
    notification_policy()
    result = CreateInAppNotification(
        recipient=active_user,
        template_code="todo.created",
        variables={"title": todo.title},
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
