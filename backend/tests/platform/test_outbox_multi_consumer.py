"""Multi-subscriber outbox registry: multiple consumers per event_type."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.platform.outbox.dispatcher import UnregisteredEventType, dispatch_pending_events
from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus
from apps.platform.outbox.tasks import LocalOutboxPublisher, merged_consumer_registry


class _RecordingConsumer:
    def __init__(self) -> None:
        self.calls = 0

    def consume(self, event: OutboxEvent) -> None:
        self.calls += 1


class _RaisingConsumer:
    def __init__(self) -> None:
        self.calls = 0

    def consume(self, event: OutboxEvent) -> None:
        self.calls += 1
        raise RuntimeError("second subscriber unavailable")


def _two_subscriber_registry(first, second):
    def _registry():
        return {"multi.subscriber.event": [("first_sub", first), ("second_sub", second)]}

    return _registry


@pytest.mark.django_db(transaction=True)
def test_merged_registry_returns_a_list_of_consumers_per_event_type() -> None:
    merged = merged_consumer_registry()
    for event_type, consumers in merged.items():
        assert isinstance(consumers, list)
        assert consumers, f"{event_type} registered with an empty consumer list"
        for entry in consumers:
            assert len(entry) == 2


@pytest.mark.django_db(transaction=True)
def test_publish_invokes_every_registered_consumer_for_the_event_type(monkeypatch) -> None:
    first = _RecordingConsumer()
    second = _RecordingConsumer()
    monkeypatch.setattr(
        "apps.platform.outbox.tasks.merged_consumer_registry",
        _two_subscriber_registry(first, second),
    )
    event = OutboxEvent.objects.create(
        event_type="multi.subscriber.event",
        aggregate_type="test",
        aggregate_id="00000000-0000-0000-0000-000000000001",
        payload_json={},
        occurred_at=timezone.now(),
    )

    LocalOutboxPublisher().publish(event)

    assert first.calls == 1
    assert second.calls == 1
    assert ConsumerReceipt.objects.filter(event=event, consumer_code="first_sub").count() == 1
    assert ConsumerReceipt.objects.filter(event=event, consumer_code="second_sub").count() == 1


@pytest.mark.django_db(transaction=True)
def test_one_failing_subscriber_does_not_replay_a_successful_sibling(monkeypatch) -> None:
    first = _RecordingConsumer()
    second = _RaisingConsumer()
    monkeypatch.setattr(
        "apps.platform.outbox.tasks.merged_consumer_registry",
        _two_subscriber_registry(first, second),
    )
    event = OutboxEvent.objects.create(
        event_type="multi.subscriber.event",
        aggregate_type="test",
        aggregate_id="00000000-0000-0000-0000-000000000002",
        payload_json={},
        occurred_at=timezone.now(),
        next_attempt_at=timezone.now() - timedelta(seconds=1),
    )

    dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=10)
    event.refresh_from_db()
    assert event.status == OutboxStatus.PENDING
    assert first.calls == 1
    assert second.calls == 1

    # Retry: the first (already-succeeded) consumer must not run again, only the
    # previously-failing second consumer should be invoked and finally succeed.
    healed_second = _RecordingConsumer()
    monkeypatch.setattr(
        "apps.platform.outbox.tasks.merged_consumer_registry",
        _two_subscriber_registry(first, healed_second),
    )
    event.next_attempt_at = timezone.now() - timedelta(seconds=1)
    event.save(update_fields=["next_attempt_at", "updated_at"])

    dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=10)
    event.refresh_from_db()

    assert event.status == OutboxStatus.PUBLISHED
    assert first.calls == 1  # not re-invoked: ConsumerReceipt already exists
    assert healed_second.calls == 1
    assert ConsumerReceipt.objects.filter(event=event).count() == 2


@pytest.mark.django_db(transaction=True)
def test_unregistered_event_type_still_fails_closed() -> None:
    event = OutboxEvent.objects.create(
        event_type="totally.unknown.event",
        aggregate_type="test",
        aggregate_id="00000000-0000-0000-0000-000000000003",
        payload_json={},
        occurred_at=timezone.now(),
    )
    with pytest.raises(UnregisteredEventType):
        LocalOutboxPublisher().publish(event)


@pytest.mark.django_db(transaction=True)
def test_no_local_subscriber_event_types_publish_without_consumers() -> None:
    from apps.operations.consumers import no_local_subscriber_event_types

    for event_type in sorted(no_local_subscriber_event_types()):
        event = OutboxEvent.objects.create(
            event_type=event_type,
            aggregate_type="test",
            aggregate_id="00000000-0000-0000-0000-000000000099",
            payload_json={},
            occurred_at=timezone.now(),
            next_attempt_at=timezone.now() - timedelta(seconds=1),
        )
        dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=10)
        event.refresh_from_db()
        assert event.status == OutboxStatus.PUBLISHED
        assert ConsumerReceipt.objects.filter(event=event).count() == 0
