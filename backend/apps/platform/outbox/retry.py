"""Shared retry bookkeeping for local projection and formal dispatch."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta

from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent, OutboxStatus

LOCAL_DISPATCH_FAILED = "LOCAL_DISPATCH_FAILED"
PUBLISH_FAILED = "PUBLISH_FAILED"


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
    """Conditionally bump attempt metadata without clobbering newer statuses.

    Uses a status-gated UPDATE so a stale in-memory instance cannot pull a row
    already moved to PROCESSING/PUBLISHED back to PENDING.
    """

    clock = now or timezone.now()
    attempt = event.attempt_count + 1
    next_at = next_attempt_at(attempt_count=attempt, now=clock)
    allowed = tuple(expected_statuses or (OutboxStatus.PENDING, OutboxStatus.PROCESSING))
    updated = OutboxEvent.objects.filter(pk=event.pk, status__in=allowed).update(
        status=OutboxStatus.PENDING,
        attempt_count=attempt,
        next_attempt_at=next_at,
        last_error_code=error_code,
    )
    if updated:
        event.status = OutboxStatus.PENDING
        event.attempt_count = attempt
        event.next_attempt_at = next_at
        event.last_error_code = error_code
        return attempt
    event.refresh_from_db(fields=["status", "attempt_count", "next_attempt_at", "last_error_code"])
    return event.attempt_count
