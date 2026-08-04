"""Dispatch pending outbox events to external brokers."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.retry import PUBLISH_FAILED, mark_pending_for_retry


class OutboxPublisher(Protocol):
    def publish(self, event: OutboxEvent) -> None:
        """Publish a single outbox event. Raise on delivery failure."""


@dataclass(frozen=True)
class PublishFailure(Exception):
    error_code: str = "PUBLISH_FAILED"


@dataclass(frozen=True)
class UnregisteredEventType(Exception):
    error_code: str = "UNREGISTERED_EVENT_TYPE"


def dispatch_pending_events(
    *,
    publisher: OutboxPublisher,
    limit: int = 100,
    event_types: Collection[str] | None = None,
) -> int:
    """Publish due pending events, optionally narrowed to specific event types.

    Narrowing exists for callers that must close one loop - a seed settling its own
    todos, an operator repairing one projection - without also draining an unrelated
    backlog they are not responsible for.
    """

    dispatched = 0
    now = timezone.now()

    with transaction.atomic():
        due = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
            status=OutboxStatus.PENDING, next_attempt_at__lte=now
        )
        if event_types is not None:
            due = due.filter(event_type__in=list(event_types))
        events = list(due.order_by("occurred_at")[:limit])
        for event in events:
            event.status = OutboxStatus.PROCESSING
            event.save(update_fields=["status", "updated_at"])

    for event in events:
        try:
            publisher.publish(event)
        except UnregisteredEventType as exc:
            with transaction.atomic():
                event.refresh_from_db()
                event.status = OutboxStatus.FAILED
                event.last_error_code = exc.error_code
                event.save(
                    update_fields=[
                        "status",
                        "last_error_code",
                        "updated_at",
                    ]
                )
            continue
        except Exception:
            with transaction.atomic():
                event.refresh_from_db()
                mark_pending_for_retry(
                    event,
                    error_code=PUBLISH_FAILED,
                    now=now,
                    expected_statuses=(OutboxStatus.PROCESSING,),
                )
            continue

        with transaction.atomic():
            event.refresh_from_db()
            event.status = OutboxStatus.PUBLISHED
            event.published_at = timezone.now()
            event.save(update_fields=["status", "published_at", "updated_at"])
            dispatched += 1

    return dispatched
