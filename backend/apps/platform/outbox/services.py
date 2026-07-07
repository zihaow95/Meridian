"""Register outbox events inside business transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.platform.outbox.models import OutboxEvent, OutboxStatus


@dataclass(frozen=True)
class OutboxMessage:
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime


def register_outbox_event(message: OutboxMessage) -> OutboxEvent:
    return OutboxEvent.objects.create(
        event_type=message.event_type,
        aggregate_type=message.aggregate_type,
        aggregate_id=message.aggregate_id,
        payload_json=message.payload,
        occurred_at=message.occurred_at,
        status=OutboxStatus.PENDING,
        next_attempt_at=message.occurred_at,
    )
