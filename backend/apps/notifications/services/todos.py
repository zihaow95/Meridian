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
                    open_slot=1,
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


@dataclass(frozen=True)
class SettleOpenTodosForSource:
    """Idempotently settle open todos and close their linked notifications.

    Completing, cancelling and expiring all release the open-dedup sentinel and
    close related notifications. A repeated settle must not reopen a closed
    notification or invent a new unread one.
    """

    organization_id: int
    source_type: str
    source_id: UUID
    status: str
    close_reason: str

    def execute(self) -> int:
        from apps.notifications.services.lifecycle import SynchronizeNotificationForSource

        if self.status not in {
            TodoStatus.COMPLETED,
            TodoStatus.CANCELLED,
            TodoStatus.EXPIRED,
        }:
            raise ValueError(f"Cannot settle open todos into {self.status}.")

        updated = Todo.objects.filter(
            organization_id=self.organization_id,
            source_type=self.source_type,
            source_id=self.source_id,
            status=TodoStatus.OPEN,
        ).update(status=self.status, open_slot=None)
        SynchronizeNotificationForSource(
            organization_id=self.organization_id,
            source_type=self.source_type,
            source_id=self.source_id,
            close_reason=self.close_reason,
        ).execute()
        return updated


@dataclass(frozen=True)
class CompleteOpenTodosForSource:
    """Idempotently complete open todos that point at a domain source."""

    organization_id: int
    source_type: str
    source_id: UUID

    def execute(self) -> int:
        return SettleOpenTodosForSource(
            organization_id=self.organization_id,
            source_type=self.source_type,
            source_id=self.source_id,
            status=TodoStatus.COMPLETED,
            close_reason="SOURCE_COMPLETED",
        ).execute()
