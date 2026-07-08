"""Transactional outbox behavior."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.platform.outbox.dispatcher import PublishFailure, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.platform.outbox.tasks import dispatch_outbox_task


class FailingPublisher:
    def publish(self, event: OutboxEvent) -> None:
        raise PublishFailure()


@pytest.mark.django_db
def test_register_outbox_event_persists_pending_record(active_user) -> None:
    event = register_outbox_event(
        OutboxMessage(
            event_type="identity.user_status_changed",
            aggregate_type="identity.user",
            aggregate_id=active_user.public_id,
            payload={"public_id": str(active_user.public_id)},
            occurred_at=timezone.now(),
        )
    )
    assert event.status == OutboxStatus.PENDING


@pytest.mark.django_db(transaction=True)
def test_publish_failure_keeps_committed_event_pending(
    outbox_event: OutboxEvent,
) -> None:
    outbox_event.next_attempt_at = timezone.now() - timedelta(seconds=1)
    outbox_event.save(update_fields=["next_attempt_at", "updated_at"])

    dispatch_pending_events(publisher=FailingPublisher(), limit=10)
    outbox_event.refresh_from_db()
    assert outbox_event.status == OutboxStatus.PENDING
    assert outbox_event.attempt_count == 1
    assert outbox_event.next_attempt_at is not None


@pytest.mark.django_db(transaction=True)
def test_unregistered_event_type_is_not_marked_published(outbox_event: OutboxEvent) -> None:
    outbox_event.event_type = "unknown.event"
    outbox_event.save(update_fields=["event_type", "updated_at"])

    dispatch_outbox_task(limit=10)

    outbox_event.refresh_from_db()
    assert outbox_event.status in {OutboxStatus.PENDING, OutboxStatus.FAILED}
    assert outbox_event.published_at is None
