"""Shared retry bookkeeping for local projection and formal dispatch."""

from __future__ import annotations

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
) -> int:
    """Bump attempt metadata and keep/return the event to PENDING for retry."""

    clock = now or timezone.now()
    attempt = event.attempt_count + 1
    event.status = OutboxStatus.PENDING
    event.attempt_count = attempt
    event.next_attempt_at = next_attempt_at(attempt_count=attempt, now=clock)
    event.last_error_code = error_code
    event.save(
        update_fields=[
            "status",
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "updated_at",
        ]
    )
    return attempt
