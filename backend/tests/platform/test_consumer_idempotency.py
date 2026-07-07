"""Outbox consumer idempotency."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.models import ConsumerReceipt
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class CountingHandler:
    def __init__(self) -> None:
        self.count = 0

    def consume(self, event: object) -> None:
        self.count += 1


@pytest.mark.django_db
def test_duplicate_consumption_is_ignored() -> None:
    event = register_outbox_event(
        OutboxMessage(
            event_type="identity.user_status_changed",
            aggregate_type="identity.user",
            aggregate_id=uuid4(),
            payload={},
            occurred_at=timezone.now(),
        )
    )
    handler = CountingHandler()
    assert consume_once(event=event, consumer_code="todo_projection", handler=handler) is True
    assert consume_once(event=event, consumer_code="todo_projection", handler=handler) is False
    assert handler.count == 1
    assert ConsumerReceipt.objects.filter(event=event).count() == 1
