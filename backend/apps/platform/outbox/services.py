"""Register outbox events inside business transactions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)


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
    write that registered the outbox row. Failures stay PENDING with attempt
    metadata so Celery (or a later dispatch) can retry loudly.
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
            now = timezone.now()
            attempt = pending.attempt_count + 1
            OutboxEvent.objects.filter(pk=event_id, status=OutboxStatus.PENDING).update(
                attempt_count=attempt,
                next_attempt_at=now + timedelta(seconds=min(60, 2**attempt)),
                last_error_code="LOCAL_DISPATCH_FAILED",
            )
            logger.exception(
                "Local outbox dispatch failed event_id=%s event_type=%s attempt=%s",
                pending.event_id,
                pending.event_type,
                attempt,
            )
            return
        OutboxEvent.objects.filter(pk=event_id, status=OutboxStatus.PENDING).update(
            status=OutboxStatus.PUBLISHED,
            published_at=timezone.now(),
            last_error_code="",
        )

    transaction.on_commit(_dispatch)
