"""Todo list API rules."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client

from apps.identity.models.user import User
from apps.notifications.models import Todo, TodoStatus


def create_todo_for(user: User, *, title: str) -> Todo:
    source_id = uuid4()
    return Todo.objects.create(
        organization=user.organization,
        assignee=user,
        todo_type="review",
        source_type="identity.user",
        source_id=source_id,
        action_code="identity.user.review",
        status=TodoStatus.OPEN,
        dedup_key=f"review:{source_id}",
        deep_link=f"/users/{source_id}",
        title=title,
    )


@pytest.mark.django_db
def test_my_todos_returns_only_current_user_todos(
    client: Client, active_user, another_active_user, grant_action
) -> None:
    grant_action(active_user, "notification.todo.read", "notification.todo")
    create_todo_for(active_user, title="Mine")
    create_todo_for(another_active_user, title="Other")

    client.force_login(active_user)
    response = client.get("/api/v1/todos/my")

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert titles == ["Mine"]


@pytest.mark.django_db
def test_my_todos_denies_user_without_permission(client: Client, active_user) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/todos/my")
    assert response.status_code == 404
