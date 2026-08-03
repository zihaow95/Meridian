"""Register outbox events inside business transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

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


def schedule_local_dispatch_after_commit(event: OutboxEvent) -> None:
    """Project local consumers only after the business transaction commits.

    Notification / todo projection failures must never roll back the business
    write that registered the outbox row. Celery (or a later dispatch) can
    retry anything left PENDING.
    """

    event_id = event.pk

    def _dispatch() -> None:
        # Imported lazily so app registries are fully loaded.
        from apps.platform.outbox.tasks import LocalOutboxPublisher

        pending = OutboxEvent.objects.filter(pk=event_id, status=OutboxStatus.PENDING).first()
        if pending is None:
            return
        try:
            LocalOutboxPublisher().publish(pending)
        except Exception:
            return
        OutboxEvent.objects.filter(pk=event_id, status=OutboxStatus.PENDING).update(
            status=OutboxStatus.PUBLISHED,
            published_at=timezone.now(),
        )

    transaction.on_commit(_dispatch)
