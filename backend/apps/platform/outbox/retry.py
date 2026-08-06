"""Shared retry bookkeeping for local projection and formal dispatch."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus

LOCAL_DISPATCH_FAILED = "LOCAL_DISPATCH_FAILED"
PUBLISH_FAILED = "PUBLISH_FAILED"
# Finite retry budget: after this many attempts the row stays FAILED and queryable.
MAX_ATTEMPTS = 8


def next_attempt_at(*, attempt_count: int, now: datetime | None = None) -> datetime:
    """Backoff shared by local after-commit projection and Celery dispatch."""

    clock = now or timezone.now()
    return clock + timedelta(seconds=min(60, 2**attempt_count))


def mark_pending_for_retry(
    event: OutboxEvent,
    *,
    error_code: str,
    now: datetime | None = None,
    expected_statuses: Collection[str] | None = None,
) -> int:
    """Atomically bump attempt metadata without clobbering newer statuses.

    Locks the row so concurrent local projection and dispatcher failures each
    observe the latest attempt_count. When the budget is exhausted, the event
    becomes FAILED so operators can query the durable failure fact.
    """

    clock = now or timezone.now()
    allowed = tuple(expected_statuses or (OutboxStatus.PENDING, OutboxStatus.PROCESSING))
    with transaction.atomic():
        locked = (
            OutboxEvent.objects.select_for_update().filter(pk=event.pk, status__in=allowed).first()
        )
        if locked is None:
            event.refresh_from_db(
                fields=[
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error_code",
                    "updated_at",
                ]
            )
            return event.attempt_count

        attempt = locked.attempt_count + 1
        locked.attempt_count = attempt
        locked.last_error_code = error_code
        locked.updated_at = clock
        if attempt >= MAX_ATTEMPTS:
            locked.status = OutboxStatus.FAILED
            locked.next_attempt_at = None
            locked.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error_code",
                    "updated_at",
                ]
            )
        else:
            locked.status = OutboxStatus.PENDING
            locked.next_attempt_at = next_attempt_at(attempt_count=attempt, now=clock)
            locked.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "next_attempt_at",
                    "last_error_code",
                    "updated_at",
                ]
            )

        event.status = locked.status
        event.attempt_count = locked.attempt_count
        event.next_attempt_at = locked.next_attempt_at
        event.last_error_code = locked.last_error_code
        event.updated_at = locked.updated_at
        return attempt
