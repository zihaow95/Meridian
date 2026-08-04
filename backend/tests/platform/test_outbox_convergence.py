"""Pending events must reach a decision when nothing is scheduled to retry them.

Phase 6 runs on a LAN without a Celery worker or beat, so "PENDING with a backoff"
describes an event nobody will ever pick up. An operator step is allowed to bring
those attempts forward, but not to hand a broken event a fresh retry budget.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.platform.outbox.convergence import converge_pending_events
from apps.platform.outbox.dispatcher import PublishFailure, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.retry import LOCAL_DISPATCH_FAILED, mark_pending_for_retry
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class AcceptingPublisher:
    def publish(self, event: OutboxEvent) -> None:
        return None


class FailingPublisher:
    def publish(self, event: OutboxEvent) -> None:
        raise PublishFailure()


@pytest.mark.django_db
def test_convergence_publishes_a_retry_the_scheduler_would_still_be_waiting_for(
    outbox_event: OutboxEvent,
) -> None:
    mark_pending_for_retry(
        outbox_event,
        error_code=LOCAL_DISPATCH_FAILED,
        expected_statuses=(OutboxStatus.PENDING,),
    )
    outbox_event.refresh_from_db()
    assert outbox_event.next_attempt_at is not None
    assert outbox_event.next_attempt_at > timezone.now()
    assert dispatch_pending_events(publisher=AcceptingPublisher(), limit=10) == 0

    report = converge_pending_events(publisher=AcceptingPublisher())

    outbox_event.refresh_from_db()
    assert outbox_event.status == OutboxStatus.PUBLISHED
    assert report.converged
    assert report.dispatched == 1
    # Forcing an earlier attempt must not look like a first attempt.
    assert outbox_event.attempt_count == 1


@pytest.mark.django_db
def test_convergence_ignores_the_loops_it_was_not_asked_to_close(
    outbox_event: OutboxEvent,
) -> None:
    """A caller closing one loop must not be blocked by an unrelated backlog.

    A long-lived database holds thousands of pending events of other types. Draining
    them is somebody else's decision, and it would also push the caller's own events
    out of the dispatch window.
    """

    mine = register_outbox_event(
        OutboxMessage(
            event_type="todo.requested",
            aggregate_type="material_confirmation",
            aggregate_id=uuid4(),
            payload={"dedup_key": "material_confirmation:x"},
            occurred_at=timezone.now(),
        )
    )

    report = converge_pending_events(
        publisher=AcceptingPublisher(), event_types=("todo.requested",)
    )

    mine.refresh_from_db()
    outbox_event.refresh_from_db()
    assert report.converged
    assert report.dispatched == 1
    assert mine.status == OutboxStatus.PUBLISHED
    assert outbox_event.status == OutboxStatus.PENDING


@pytest.mark.django_db
def test_convergence_reports_the_event_it_could_not_deliver(outbox_event: OutboxEvent) -> None:
    report = converge_pending_events(publisher=FailingPublisher())

    outbox_event.refresh_from_db()
    assert not report.converged
    assert report.dispatched == 0
    assert outbox_event.status == OutboxStatus.PENDING
    assert outbox_event.attempt_count == 1
    described = report.undelivered[0].describe()
    assert "identity.user_status_changed" in described
    assert LOCAL_DISPATCH_FAILED in described or "PUBLISH_FAILED" in described
