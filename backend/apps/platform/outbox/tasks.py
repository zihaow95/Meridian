"""Celery tasks for outbox dispatch."""

from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]

from apps.notifications.consumers import local_consumer_registry as notifications_registry
from apps.operations.consumers import local_consumer_registry as operations_registry
from apps.platform.outbox.consumer import OutboxConsumer, consume_once
from apps.platform.outbox.dispatcher import UnregisteredEventType, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent


def merged_consumer_registry() -> dict[str, tuple[str, OutboxConsumer]]:
    return {**notifications_registry(), **operations_registry()}


class LocalOutboxPublisher:
    def publish(self, event: OutboxEvent) -> None:
        entry = merged_consumer_registry().get(event.event_type)
        if entry is None:
            raise UnregisteredEventType()
        consumer_code, handler = entry
        consume_once(event=event, consumer_code=consumer_code, handler=handler)


@shared_task(name="platform.dispatch_outbox")
def dispatch_outbox_task(limit: int = 100) -> int:
    return dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=limit)
