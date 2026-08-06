"""Bring pending outbox events to a decision without waiting for a worker.

Backoff exists so a failing consumer is not hammered by a scheduler. An operator
step that must hand back a decided system - a seed, a deployment, a repair - is
allowed to bring the next attempt forward instead, because "PENDING and therefore
retryable" is not a closed loop when nothing is running to retry it.

The attempt budget is never refilled: forcing an earlier attempt must not let a
genuinely broken event escape becoming FAILED and queryable. Convergence keeps
attempting until every event in scope leaves PENDING, so a bad event spends its
whole budget here rather than being handed back as "still retryable, one day".

Scope is mandatory and is a list of exact event ids. Draining every row of a given
type across the database would let one organization's operator step publish another
organization's business events, and would let a stranger's failing event block the
caller's own loop.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.platform.outbox.dispatcher import OutboxPublisher, dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.retry import MAX_ATTEMPTS

# Enough rounds for one event to spend its whole retry budget, plus room for a
# chain where each success unblocks the next event.
DEFAULT_MAX_ROUNDS = MAX_ATTEMPTS + 4


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
    event_ids: Collection[int],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    limit: int = 200,
) -> ConvergenceReport:
    """Attempt every pending event in scope until none is left PENDING.

    Rounds matter because one event can unblock another: a settlement whose todo
    is not projected yet only succeeds after the projection event ahead of it does.

    A round that publishes nothing is not the end of the loop - a rejected event
    that spent an attempt is progress, and the next round must take the following
    attempt so the event can reach FAILED inside this call. Only a round that
    neither publishes nor attempts anything ends the loop.

    Scope is the exact rows the caller owns. Naming a type instead would put every
    organization holding that type inside one caller's decision, so there is no
    interface for it here: a caller resolves its own ids first.
    """

    if not event_ids:
        return ConvergenceReport(dispatched=0, rounds=0, undelivered=())

    scope = _ScopedEvents(event_ids=event_ids)
    dispatched = 0
    rounds = 0
    while rounds < max_rounds and scope.pending().exists():
        rounds += 1
        before = scope.progress_marker()
        now = timezone.now()
        # A PENDING row with no scheduled attempt, or one scheduled for later, is
        # invisible to the dispatcher; bring both into this attempt.
        scope.pending().filter(Q(next_attempt_at__gt=now) | Q(next_attempt_at__isnull=True)).update(
            next_attempt_at=now, updated_at=now
        )
        moved = dispatch_pending_events(publisher=publisher, limit=limit, event_ids=event_ids)
        dispatched += moved
        if moved == 0 and scope.progress_marker() == before:
            break

    undelivered = tuple(
        UndeliveredEvent(
            event_type=event.event_type,
            aggregate_id=str(event.aggregate_id),
            status=event.status,
            attempt_count=event.attempt_count,
            last_error_code=event.last_error_code,
        )
        for event in scope.all()
        .filter(
            status__in=[OutboxStatus.PENDING, OutboxStatus.PROCESSING, OutboxStatus.FAILED],
        )
        .order_by("occurred_at", "pk")
    )
    return ConvergenceReport(dispatched=dispatched, rounds=rounds, undelivered=undelivered)


@dataclass(frozen=True)
class _ScopedEvents:
    event_ids: Collection[int]

    def all(self) -> QuerySet[OutboxEvent]:
        return OutboxEvent.objects.filter(pk__in=list(self.event_ids))

    def pending(self) -> QuerySet[OutboxEvent]:
        return self.all().filter(status=OutboxStatus.PENDING)

    def progress_marker(self) -> tuple[int, int]:
        """What changed in a round: rows still pending, and attempts spent so far."""

        spent = 0
        remaining = 0
        for status, attempt_count in self.all().values_list("status", "attempt_count"):
            spent += attempt_count
            if status == OutboxStatus.PENDING:
                remaining += 1
        return remaining, spent
