"""Outbox consumers projecting todos from domain events."""

from __future__ import annotations

from apps.notifications.services.todos import UpsertOpenTodo, build_todo_event_from_outbox
from apps.platform.outbox.models import OutboxEvent


class TodoProjectionConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "todo.requested":
            return
        todo_event = build_todo_event_from_outbox(event.payload_json)
        UpsertOpenTodo(event=todo_event).execute()
