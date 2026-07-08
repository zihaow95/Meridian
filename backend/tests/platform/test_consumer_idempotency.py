"""Outbox consumer idempotency."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.models import ConsumerReceipt
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class CountingHandler:
    def __init__(self) -> None:
        self.count = 0

    def consume(self, event: object) -> None:
        self.count += 1


class FailingHandler:
    def consume(self, event: object) -> None:
        raise RuntimeError("handler failed")


@pytest.mark.django_db
def test_duplicate_consumption_is_ignored() -> None:
    event = register_outbox_event(
        OutboxMessage(
            event_type="identity.user_status_changed",
            aggregate_type="identity.user",
            aggregate_id=uuid4(),
            payload={},
            occurred_at=timezone.now(),
        )
    )
    handler = CountingHandler()
    assert consume_once(event=event, consumer_code="todo_projection", handler=handler) is True
    assert consume_once(event=event, consumer_code="todo_projection", handler=handler) is False
    assert handler.count == 1
    assert ConsumerReceipt.objects.filter(event=event).count() == 1


@pytest.mark.django_db(transaction=True)
def test_consumer_receipt_is_not_written_when_handler_fails(outbox_event) -> None:
    handler = FailingHandler()

    with pytest.raises(RuntimeError):
        consume_once(event=outbox_event, consumer_code="todo_projection", handler=handler)

    assert (
        ConsumerReceipt.objects.filter(
            event=outbox_event,
            consumer_code="todo_projection",
        ).count()
        == 0
    )


@pytest.mark.django_db(transaction=True)
def test_handler_failure_allows_retry(outbox_event) -> None:
    class FailOnceHandler:
        def __init__(self) -> None:
            self.calls = 0

        def consume(self, event: object) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("fail once")

    handler = FailOnceHandler()
    with pytest.raises(RuntimeError):
        consume_once(event=outbox_event, consumer_code="todo_projection", handler=handler)
    assert ConsumerReceipt.objects.filter(event=outbox_event).count() == 0

    assert (
        consume_once(event=outbox_event, consumer_code="todo_projection", handler=handler) is True
    )
    assert handler.calls == 2
    assert ConsumerReceipt.objects.filter(event=outbox_event).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_consumers_execute_handler_once(outbox_event) -> None:
    import threading

    from django.db import close_old_connections, connections

    class BlockingHandler:
        def __init__(self) -> None:
            self.calls = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        def consume(self, event: object) -> None:
            self.calls += 1
            self.entered.set()
            assert self.release.wait(timeout=5)

    handler = BlockingHandler()
    results: list[bool] = []
    errors: list[BaseException] = []

    def run_consume() -> None:
        close_old_connections()
        try:
            results.append(
                consume_once(
                    event=outbox_event,
                    consumer_code="todo_projection",
                    handler=handler,
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    first = threading.Thread(target=run_consume)
    second = threading.Thread(target=run_consume)

    first.start()
    assert handler.entered.wait(timeout=5)

    second.start()
    handler.release.set()

    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    assert sorted(results) == [False, True]
    assert handler.calls == 1
    assert ConsumerReceipt.objects.filter(event=outbox_event).count() == 1
