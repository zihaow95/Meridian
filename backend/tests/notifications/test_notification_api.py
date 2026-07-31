"""Recipient-isolated notification list, unread count, read and close."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.notifications.services.lifecycle import MarkNotificationRead
from apps.platform.application.command import CommandContext

pytestmark = pytest.mark.django_db


@pytest.fixture
def grant_notification_read(active_user, grant_action):
    grant_action(active_user, "notification.message.read", "notification.message")
    return active_user


@pytest.fixture
def grant_notification_write(active_user, grant_action):
    grant_action(active_user, "notification.message.read", "notification.message")
    grant_action(active_user, "notification.message.mark_read", "notification.message")
    grant_action(active_user, "notification.message.close", "notification.message")
    return active_user


def test_my_notifications_return_only_the_recipients_rows(
    client: Client,
    grant_notification_read,
    another_active_user,
    grant_action,
    notification,
    allow_notification,
    notification_templates,
    notification_policy,
) -> None:
    grant_action(another_active_user, "notification.message.read", "notification.message")
    from apps.notifications.services.notifications import CreateInAppNotification

    notification_templates()
    notification_policy()
    CreateInAppNotification(
        recipient=another_active_user,
        template_code="todo.created",
        variables={"title": "Other"},
        object_type="identity.user",
        object_id=another_active_user.public_id,
        dedup_key="notify:other",
        deep_link="/users/other",
        action_code="notification.read",
    ).execute()

    client.force_login(grant_notification_read)
    response = client.get("/api/v1/notifications/my")

    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 1
    assert [row["summary"] for row in body["items"]] == [notification.summary]
    assert "object_id" not in body["items"][0]
    assert set(body["items"][0]) >= {
        "public_id",
        "summary",
        "category",
        "level",
        "status",
        "deep_link",
        "created_at",
    }


def test_my_notifications_filter_by_status_category_and_level(
    client: Client, grant_notification_read, notification
) -> None:
    client.force_login(grant_notification_read)
    response = client.get(
        "/api/v1/notifications/my",
        {"status": "UNREAD", "category": "ACTION_REQUIRED", "level": "IMPORTANT"},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    empty = client.get("/api/v1/notifications/my", {"status": "CLOSED"})
    assert empty.json()["items"] == []
    assert empty.json()["unread_count"] == 1


def test_unread_count_ignores_read_and_closed_rows(
    client: Client, grant_notification_write, notification
) -> None:
    MarkNotificationRead(
        context=CommandContext.for_actor(grant_notification_write),
        notification_public_id=notification.public_id,
    ).execute()

    client.force_login(grant_notification_write)
    response = client.get("/api/v1/notifications/my")

    assert response.json()["unread_count"] == 0


def test_mark_read_is_recipient_only_and_idempotent(
    client: Client, grant_notification_write, another_active_user, grant_action, notification
) -> None:
    grant_action(another_active_user, "notification.message.mark_read", "notification.message")
    client.force_login(another_active_user)
    denied = client.post(f"/api/v1/notifications/{notification.public_id}/read")
    assert denied.status_code == 404

    client.force_login(grant_notification_write)
    first = client.post(f"/api/v1/notifications/{notification.public_id}/read")
    second = client.post(f"/api/v1/notifications/{notification.public_id}/read")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "READ"
    assert second.json()["read_at"] == first.json()["read_at"]


def test_close_keeps_the_first_reason(
    client: Client, grant_notification_write, notification
) -> None:
    client.force_login(grant_notification_write)
    first = client.post(
        f"/api/v1/notifications/{notification.public_id}/close",
        data={"close_reason": "DONE"},
        content_type="application/json",
    )
    second = client.post(
        f"/api/v1/notifications/{notification.public_id}/close",
        data={"close_reason": "AGAIN"},
        content_type="application/json",
    )

    assert first.status_code == 200
    assert second.json()["close_reason"] == "DONE"


def test_list_is_refused_without_the_read_action(client: Client, active_user, notification) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/notifications/my")
    assert response.status_code == 404


def test_my_todos_surface_category_level_and_due(
    client: Client, active_user, grant_action, notification, todo
) -> None:
    grant_action(active_user, "notification.todo.read", "notification.todo")
    client.force_login(active_user)

    response = client.get("/api/v1/todos/my")

    assert response.status_code == 200
    row = next(item for item in response.json() if item["public_id"] == str(todo.public_id))
    assert row["category"] == notification.category
    assert row["level"] == notification.level
    assert "due_at" in row
    assert "status" in row
