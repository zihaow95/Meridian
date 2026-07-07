"""Dispatch pending outbox events to external brokers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus


class OutboxPublisher(Protocol):
    def publish(self, event: OutboxEvent) -> None:
        """Publish a single outbox event. Raise on delivery failure."""


@dataclass(frozen=True)
class PublishFailure(Exception):
    error_code: str = "PUBLISH_FAILED"


def dispatch_pending_events(*, publisher: OutboxPublisher, limit: int = 100) -> int:
    dispatched = 0
    now = timezone.now()

    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(status=OutboxStatus.PENDING, next_attempt_at__lte=now)
            .order_by("occurred_at")[:limit]
        )
        for event in events:
            event.status = OutboxStatus.PROCESSING
            event.save(update_fields=["status", "updated_at"])

    for event in events:
        try:
            publisher.publish(event)
        except Exception:
            with transaction.atomic():
                event.refresh_from_db()
                event.status = OutboxStatus.PENDING
                event.attempt_count += 1
                event.next_attempt_at = now + timedelta(seconds=min(60, 2**event.attempt_count))
                event.last_error_code = "PUBLISH_FAILED"
                event.save(
                    update_fields=[
                        "status",
                        "attempt_count",
                        "next_attempt_at",
                        "last_error_code",
                        "updated_at",
                    ]
                )
            continue

        with transaction.atomic():
            event.refresh_from_db()
            event.status = OutboxStatus.PUBLISHED
            event.published_at = timezone.now()
            event.save(update_fields=["status", "published_at", "updated_at"])
            dispatched += 1

    return dispatched
