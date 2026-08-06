"""Celery tasks for outbox dispatch."""

from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]

from apps.notifications.consumers import local_consumer_registry as notifications_registry
from apps.operations.consumers import local_consumer_registry as operations_registry
from apps.operations.consumers import no_local_subscriber_event_types
from apps.platform.outbox.consumer import OutboxConsumer, consume_once
from apps.platform.outbox.dispatcher import UnregisteredEventType, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent
from apps.products.consumers import local_consumer_registry as products_registry


def merged_consumer_registry() -> dict[str, list[tuple[str, OutboxConsumer]]]:
    merged: dict[str, list[tuple[str, OutboxConsumer]]] = {}
    for registry in (notifications_registry(), operations_registry(), products_registry()):
        for event_type, consumers in registry.items():
            merged.setdefault(event_type, []).extend(consumers)
    return merged


class LocalOutboxPublisher:
    def publish(self, event: OutboxEvent) -> None:
        if event.event_type in no_local_subscriber_event_types():
            return
        consumers = merged_consumer_registry().get(event.event_type)
        if not consumers:
            raise UnregisteredEventType()
        for consumer_code, handler in consumers:
            consume_once(event=event, consumer_code=consumer_code, handler=handler)


@shared_task(name="platform.dispatch_outbox")
def dispatch_outbox_task(limit: int = 100) -> int:
    return dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=limit)
