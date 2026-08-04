"""Pending events must reach a decision when nothing is scheduled to retry them.

Phase 6 runs on a LAN without a Celery worker or beat, so "PENDING with a backoff"
describes an event nobody will ever pick up. An operator step is allowed to bring
those attempts forward, but not to hand a broken event a fresh retry budget, and
not to touch events belonging to loops it was not asked to close.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.platform.outbox.convergence import converge_pending_events
from apps.platform.outbox.dispatcher import PublishFailure, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.retry import LOCAL_DISPATCH_FAILED, MAX_ATTEMPTS, mark_pending_for_retry
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class AcceptingPublisher:
    def publish(self, event: OutboxEvent) -> None:
        return None


class FailingPublisher:
    def publish(self, event: OutboxEvent) -> None:
        raise PublishFailure()


def _todo_event() -> OutboxEvent:
    return register_outbox_event(
        OutboxMessage(
            event_type="todo.requested",
            aggregate_type="material_confirmation",
            aggregate_id=uuid4(),
            payload={"dedup_key": "material_confirmation:x"},
            occurred_at=timezone.now(),
        )
    )


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

    report = converge_pending_events(publisher=AcceptingPublisher(), event_ids=[outbox_event.pk])

    outbox_event.refresh_from_db()
    assert outbox_event.status == OutboxStatus.PUBLISHED
    assert report.converged
    assert report.dispatched == 1
    # Forcing an earlier attempt must not look like a first attempt.
    assert outbox_event.attempt_count == 1


@pytest.mark.django_db
def test_convergence_refuses_to_drain_events_nobody_named() -> None:
    """Without a scope, one organization's operator step moves everybody's facts."""

    with pytest.raises(ValueError):
        converge_pending_events(publisher=AcceptingPublisher())


@pytest.mark.django_db
def test_convergence_ignores_the_loops_it_was_not_asked_to_close(
    outbox_event: OutboxEvent,
) -> None:
    """A caller closing one loop must not be blocked by an unrelated backlog.

    A long-lived database holds thousands of pending events of other types. Draining
    them is somebody else's decision, and it would also push the caller's own events
    out of the dispatch window.
    """

    mine = _todo_event()

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
def test_convergence_leaves_a_same_type_event_it_was_not_given() -> None:
    """Type is not ownership: another organization's todo is not this caller's to move."""

    mine = _todo_event()
    somebody_elses = _todo_event()

    report = converge_pending_events(publisher=AcceptingPublisher(), event_ids=[mine.pk])

    mine.refresh_from_db()
    somebody_elses.refresh_from_db()
    assert report.dispatched == 1
    assert mine.status == OutboxStatus.PUBLISHED
    assert somebody_elses.status == OutboxStatus.PENDING
    assert somebody_elses.attempt_count == 0


@pytest.mark.django_db
def test_a_broken_event_spends_its_whole_budget_before_being_handed_back(
    outbox_event: OutboxEvent,
) -> None:
    """Convergence owes the caller a decided event, not another promise to retry.

    A round that publishes nothing still made progress if it spent an attempt, so
    the loop must keep going until the event is FAILED and queryable. Stopping at the
    first failure would leave a PENDING row nobody will ever pick up again.
    """

    report = converge_pending_events(publisher=FailingPublisher(), event_ids=[outbox_event.pk])

    outbox_event.refresh_from_db()
    assert not report.converged
    assert report.dispatched == 0
    assert outbox_event.status == OutboxStatus.FAILED
    assert outbox_event.attempt_count == MAX_ATTEMPTS
    assert report.rounds == MAX_ATTEMPTS
    described = report.undelivered[0].describe()
    assert "identity.user_status_changed" in described
    assert LOCAL_DISPATCH_FAILED in described or "PUBLISH_FAILED" in described


@pytest.mark.django_db
def test_convergence_stops_when_a_round_can_neither_publish_nor_attempt(
    outbox_event: OutboxEvent,
) -> None:
    """A round that changes nothing ends the loop instead of spinning."""

    OutboxEvent.objects.filter(pk=outbox_event.pk).update(status=OutboxStatus.PROCESSING)

    report = converge_pending_events(publisher=FailingPublisher(), event_ids=[outbox_event.pk])

    outbox_event.refresh_from_db()
    assert report.rounds == 0
    assert outbox_event.status == OutboxStatus.PROCESSING
    assert [item.status for item in report.undelivered] == [OutboxStatus.PROCESSING]
