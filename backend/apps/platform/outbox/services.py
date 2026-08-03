"""Register outbox events inside business transactions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.retry import LOCAL_DISPATCH_FAILED, mark_pending_for_retry
from apps.platform.request_context import get_or_create_trace_id

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
            attempt = mark_pending_for_retry(
                pending,
                error_code=LOCAL_DISPATCH_FAILED,
                now=now,
                expected_statuses=(OutboxStatus.PENDING,),
            )
            logger.exception(
                "outbox.local_dispatch_failed",
                extra={
                    "event_code": LOCAL_DISPATCH_FAILED,
                    "trace_id": get_or_create_trace_id(),
                    "event_id": str(pending.event_id),
                    "event_type": pending.event_type,
                    "aggregate_type": pending.aggregate_type,
                    "aggregate_id": str(pending.aggregate_id),
                    "attempt": attempt,
                    "last_error_code": LOCAL_DISPATCH_FAILED,
                },
            )
            return
        OutboxEvent.objects.filter(pk=event_id, status=OutboxStatus.PENDING).update(
            status=OutboxStatus.PUBLISHED,
            published_at=timezone.now(),
            last_error_code="",
        )

    transaction.on_commit(_dispatch)
