"""Celery tasks for outbox dispatch."""

from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]

from apps.notifications.consumers import local_consumer_registry
from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.dispatcher import UnregisteredEventType, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent


class LocalOutboxPublisher:
    def publish(self, event: OutboxEvent) -> None:
        entry = local_consumer_registry().get(event.event_type)
        if entry is None:
            raise UnregisteredEventType()
        consumer_code, handler = entry
        consume_once(event=event, consumer_code=consumer_code, handler=handler)


@shared_task(name="platform.dispatch_outbox")
def dispatch_outbox_task(limit: int = 100) -> int:
    return dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=limit)
