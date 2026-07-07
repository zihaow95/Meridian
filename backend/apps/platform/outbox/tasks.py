"""Celery tasks for outbox dispatch."""

from __future__ import annotations

from celery import shared_task  # type: ignore[import-untyped]

from apps.platform.outbox.dispatcher import dispatch_pending_events


class CeleryOutboxPublisher:
    def publish(self, event: object) -> None:
        del event
        return None


@shared_task(name="platform.dispatch_outbox")
def dispatch_outbox_task(limit: int = 100) -> int:
    return dispatch_pending_events(publisher=CeleryOutboxPublisher(), limit=limit)
