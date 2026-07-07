"""Authoritative todo projection."""

from __future__ import annotations

import pytest

from apps.notifications.models import Todo, TodoStatus
from apps.platform.outbox.consumer import consume_once


@pytest.mark.django_db
def test_duplicate_event_creates_one_open_todo(event, todo_consumer, active_user) -> None:
    consume_once(event=event, consumer_code="todo_projection", handler=todo_consumer)
    consume_once(event=event, consumer_code="todo_projection", handler=todo_consumer)
    assert Todo.objects.filter(assignee=active_user, status=TodoStatus.OPEN).count() == 1
