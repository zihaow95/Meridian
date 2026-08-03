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


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_increment_attempt_count_atomically(
    outbox_event: OutboxEvent,
) -> None:
    import threading

    from django.db import close_old_connections, connections

    from apps.platform.outbox.retry import LOCAL_DISPATCH_FAILED, mark_pending_for_retry

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _retry() -> None:
        close_old_connections()
        try:
            stale = OutboxEvent.objects.get(pk=outbox_event.pk)
            barrier.wait(timeout=10)
            mark_pending_for_retry(
                stale,
                error_code=LOCAL_DISPATCH_FAILED,
                expected_statuses=(OutboxStatus.PENDING, OutboxStatus.PROCESSING),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_retry)
    t2 = threading.Thread(target=_retry)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == []
    outbox_event.refresh_from_db()
    assert outbox_event.attempt_count == 2
    assert outbox_event.updated_at is not None


@pytest.mark.django_db
def test_retry_marks_failed_after_max_attempts(outbox_event: OutboxEvent) -> None:
    from apps.platform.outbox.retry import (
        LOCAL_DISPATCH_FAILED,
        MAX_ATTEMPTS,
        mark_pending_for_retry,
    )

    outbox_event.attempt_count = MAX_ATTEMPTS - 1
    outbox_event.save(update_fields=["attempt_count", "updated_at"])

    attempt = mark_pending_for_retry(
        outbox_event,
        error_code=LOCAL_DISPATCH_FAILED,
        expected_statuses=(OutboxStatus.PENDING,),
    )

    outbox_event.refresh_from_db()
    assert attempt == MAX_ATTEMPTS
    assert outbox_event.status == OutboxStatus.FAILED
    assert outbox_event.last_error_code == LOCAL_DISPATCH_FAILED
    assert outbox_event.attempt_count == MAX_ATTEMPTS


@pytest.mark.django_db(transaction=True)
def test_local_retry_does_not_clobber_a_concurrent_published_status(
    outbox_event: OutboxEvent,
) -> None:
    """A stale PENDING instance must not pull a published row back to PENDING."""

    import threading

    from django.db import close_old_connections, connections

    from apps.platform.outbox.retry import LOCAL_DISPATCH_FAILED, mark_pending_for_retry

    stale = OutboxEvent.objects.get(pk=outbox_event.pk)
    assert stale.status == OutboxStatus.PENDING

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def publish_wins() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            OutboxEvent.objects.filter(pk=outbox_event.pk).update(
                status=OutboxStatus.PUBLISHED,
                published_at=timezone.now(),
                last_error_code="",
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    def stale_retry() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            # Simulate a local callback holding a pre-race PENDING instance.
            mark_pending_for_retry(
                stale,
                error_code=LOCAL_DISPATCH_FAILED,
                expected_statuses=(OutboxStatus.PENDING,),
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=publish_wins)
    t2 = threading.Thread(target=stale_retry)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == []
    outbox_event.refresh_from_db()
    assert outbox_event.status == OutboxStatus.PUBLISHED
    assert outbox_event.last_error_code == ""
