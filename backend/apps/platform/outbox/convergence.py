"""Bring pending outbox events to a decision without waiting for a worker.

Backoff exists so a failing consumer is not hammered by a scheduler. An operator
step that must hand back a decided system - a seed, a deployment, a repair - is
allowed to bring the next attempt forward instead, because "PENDING and therefore
retryable" is not a closed loop when nothing is running to retry it.

The attempt budget is never refilled: forcing an earlier attempt must not let a
genuinely broken event escape becoming FAILED and queryable.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.platform.outbox.dispatcher import OutboxPublisher, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus

DEFAULT_MAX_ROUNDS = 6


@dataclass(frozen=True)
class UndeliveredEvent:
    event_type: str
    aggregate_id: str
    status: str
    attempt_count: int
    last_error_code: str

    def describe(self) -> str:
        return (
            f"{self.event_type} on {self.aggregate_id} is {self.status} "
            f"after {self.attempt_count} attempt(s), last error "
            f"{self.last_error_code or 'NONE'}"
        )


@dataclass(frozen=True)
class ConvergenceReport:
    dispatched: int
    rounds: int
    undelivered: tuple[UndeliveredEvent, ...]

    @property
    def converged(self) -> bool:
        return not self.undelivered


def converge_pending_events(
    *,
    publisher: OutboxPublisher,
    event_types: Collection[str] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    limit: int = 200,
) -> ConvergenceReport:
    """Dispatch pending events, including backed-off retries, until nothing moves.

    Rounds matter because one event can unblock another: a settlement whose todo
    is not projected yet only succeeds after the projection event ahead of it does.

    `event_types` keeps a caller to the loop it owns. A seed that must settle its own
    todos has no business draining an unrelated backlog, and would in any case be
    pushed off the end of the dispatch window by it.
    """

    dispatched = 0
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        if not _undecided(event_types).filter(status=OutboxStatus.PENDING).exists():
            break
        now = timezone.now()
        # A PENDING row with no scheduled attempt, or one scheduled for later, is
        # invisible to the dispatcher; bring both into this attempt.
        _undecided(event_types).filter(status=OutboxStatus.PENDING).filter(
            Q(next_attempt_at__gt=now) | Q(next_attempt_at__isnull=True)
        ).update(next_attempt_at=now, updated_at=now)
        moved = dispatch_pending_events(publisher=publisher, limit=limit, event_types=event_types)
        dispatched += moved
        if moved == 0:
            break

    undelivered = tuple(
        UndeliveredEvent(
            event_type=event.event_type,
            aggregate_id=str(event.aggregate_id),
            status=event.status,
            attempt_count=event.attempt_count,
            last_error_code=event.last_error_code,
        )
        for event in _undecided(event_types)
        .filter(
            status__in=[OutboxStatus.PENDING, OutboxStatus.PROCESSING, OutboxStatus.FAILED],
        )
        .order_by("occurred_at", "pk")
    )
    return ConvergenceReport(dispatched=dispatched, rounds=rounds, undelivered=undelivered)


def _undecided(event_types: Collection[str] | None) -> QuerySet[OutboxEvent]:
    events = OutboxEvent.objects.all()
    if event_types is not None:
        events = events.filter(event_type__in=list(event_types))
    return events
