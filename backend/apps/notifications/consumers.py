"""Outbox consumers projecting todos and linked in-app notifications."""

from __future__ import annotations

from django.db import transaction

from apps.identity.models.user import User
from apps.notifications.services.notifications import CreateInAppNotification
from apps.notifications.services.todos import UpsertOpenTodo, build_todo_event_from_outbox
from apps.platform.outbox.consumer import OutboxConsumer
from apps.platform.outbox.models import OutboxEvent


class TodoProjectionConsumer:
    """Project an actionable todo and its authoritative in-app notification.

    Business services emit ``todo.requested``. The notification is created here
    (not only from seeds/tests) so the longitudinal path
    event → todo → in-app message → settle stays closed.
    """

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "todo.requested":
            return
        todo_event = build_todo_event_from_outbox(event.payload_json)
        with transaction.atomic():
            todo = UpsertOpenTodo(event=todo_event).execute()
            assignee = User.objects.select_related("organization").get(pk=todo_event.assignee_id)
            template_code = str(event.payload_json.get("template_code") or "todo.created")
            # Level comes only from the published template catalog. A business
            # event that carried `level` would bypass versioned classification.
            CreateInAppNotification(
                recipient=assignee,
                template_code=template_code,
                variables={"title": todo_event.title},
                object_type=todo_event.source_type,
                object_id=todo_event.source_id,
                dedup_key=f"notify:{todo_event.dedup_key}",
                deep_link=todo_event.deep_link,
                todo=todo,
                action_code=todo_event.action_code,
            ).execute()


def local_consumer_registry() -> dict[str, list[tuple[str, OutboxConsumer]]]:
    return {
        "todo.requested": [("todo_projection", TodoProjectionConsumer())],
    }
