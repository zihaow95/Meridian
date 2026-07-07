"""Todo projection from domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.identity.models.user import User
from apps.notifications.models import Todo, TodoStatus


@dataclass(frozen=True)
class TodoEvent:
    assignee_id: int
    organization_id: int
    todo_type: str
    source_type: str
    source_id: UUID
    action_code: str
    dedup_key: str
    deep_link: str
    title: str
    due_at: datetime | None = None


@dataclass(frozen=True)
class UpsertOpenTodo:
    event: TodoEvent

    def execute(self) -> Todo:
        assignee = User.objects.get(pk=self.event.assignee_id)
        try:
            with transaction.atomic():
                return Todo.objects.create(
                    organization_id=self.event.organization_id,
                    assignee=assignee,
                    todo_type=self.event.todo_type,
                    source_type=self.event.source_type,
                    source_id=self.event.source_id,
                    action_code=self.event.action_code,
                    status=TodoStatus.OPEN,
                    due_at=self.event.due_at,
                    dedup_key=self.event.dedup_key,
                    deep_link=self.event.deep_link,
                    title=self.event.title,
                )
        except IntegrityError:
            return Todo.objects.get(
                assignee_id=self.event.assignee_id,
                dedup_key=self.event.dedup_key,
                status=TodoStatus.OPEN,
            )


def build_todo_event_from_outbox(payload: dict[str, Any]) -> TodoEvent:
    return TodoEvent(
        assignee_id=int(payload["assignee_id"]),
        organization_id=int(payload["organization_id"]),
        todo_type=str(payload["todo_type"]),
        source_type=str(payload["source_type"]),
        source_id=UUID(str(payload["source_id"])),
        action_code=str(payload["action_code"]),
        dedup_key=str(payload["dedup_key"]),
        deep_link=str(payload["deep_link"]),
        title=str(payload["title"]),
        due_at=None,
    )
