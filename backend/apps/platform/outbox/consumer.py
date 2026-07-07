"""Idempotent outbox event consumption."""

from __future__ import annotations

from typing import Protocol

from django.db import IntegrityError, transaction

from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent


class OutboxConsumer(Protocol):
    def consume(self, event: OutboxEvent) -> None: ...


def consume_once(*, event: OutboxEvent, consumer_code: str, handler: OutboxConsumer) -> bool:
    try:
        with transaction.atomic():
            ConsumerReceipt.objects.create(event=event, consumer_code=consumer_code)
    except IntegrityError:
        return False

    handler.consume(event)
    return True
