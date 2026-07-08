"""Idempotent outbox event consumption."""

from __future__ import annotations

from typing import Protocol

from django.db import transaction

from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent


class OutboxConsumer(Protocol):
    def consume(self, event: OutboxEvent) -> None: ...


def consume_once(*, event: OutboxEvent, consumer_code: str, handler: OutboxConsumer) -> bool:
    with transaction.atomic():
        locked_event = OutboxEvent.objects.select_for_update().get(pk=event.pk)

        if ConsumerReceipt.objects.filter(
            event=locked_event,
            consumer_code=consumer_code,
        ).exists():
            return False

        handler.consume(locked_event)

        ConsumerReceipt.objects.create(
            event=locked_event,
            consumer_code=consumer_code,
        )
        return True
