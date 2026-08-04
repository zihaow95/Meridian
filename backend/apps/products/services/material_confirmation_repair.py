"""Repair confirmation todos an earlier build settled into thin air.

A build that settled decisions inside the deciding transaction could record a
consumer receipt for `material_confirmation.decided` while the request's own todo
was still unprojected. The settlement closed nothing, and the receipt now blocks a
replay: the material reads APPROVED while its confirmation todo stays OPEN.

Receipts and the events they describe are history and are kept. The repair is a new
event on the same confirmation, which earns its own receipt and is validated by the
same consumer as any other settlement.

The command never decides its own scope. Callers name the exact confirmations they
are answering for - a seed its own fixture, an operator the candidates a report
listed - because a repair moves real business facts and a sweep of "everything open
in this organization" would move facts nobody asked about.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.notifications.models import Todo, TodoStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.services import (
    OutboxMessage,
    register_outbox_event,
    schedule_local_dispatch_after_commit,
)
from apps.products.models import (
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialConfirmationSettlementRepair,
)
from apps.products.services.material_confirmations import confirmation_todo_dedup_key

REISSUE_REASON = "SETTLEMENT_RECEIPT_WITHOUT_TODO"
_TODO_DEDUP_PREFIX = "material_confirmation:"


def stranded_settlement_candidates(*, organization_id: int) -> list[UUID]:
    """Report decided confirmations whose todo is still open. Read-only.

    Separate from the repair so the decision to move business facts is taken by a
    caller with a scope, not by a scan. An operations command lists candidates,
    then repairs the ones it names.
    """

    candidates: list[UUID] = []
    for dedup_key in (
        Todo.objects.filter(
            organization_id=organization_id,
            status=TodoStatus.OPEN,
            dedup_key__startswith=_TODO_DEDUP_PREFIX,
        )
        .order_by("pk")
        .values_list("dedup_key", flat=True)
    ):
        confirmation_id = _confirmation_id_in(dedup_key)
        if confirmation_id is None:
            continue
        decided = (
            MaterialConfirmation.objects.filter(
                public_id=confirmation_id,
                organization_id=organization_id,
            )
            .exclude(decision=MaterialConfirmationDecision.PENDING)
            .exists()
        )
        if decided:
            candidates.append(confirmation_id)
    return candidates


@dataclass(frozen=True)
class ReissueSettlementForDecidedConfirmations:
    """Re-emit a precise settlement for the named decided confirmations."""

    context: CommandContext
    confirmation_public_ids: Collection[UUID]

    def execute(self) -> list[UUID]:
        reissued: list[UUID] = []
        for confirmation_id in _ordered(self.confirmation_public_ids):
            if self._reissue_one(confirmation_id):
                reissued.append(confirmation_id)
        return reissued

    def _reissue_one(self, confirmation_id: UUID) -> bool:
        """One repair, one transaction: a failure must not undo earlier repairs."""

        actor = self.context.actor
        try:
            with transaction.atomic():
                # Lock the confirmation first, then its todo: the settle path takes
                # the same order, so a concurrent repair queues instead of racing.
                confirmation = (
                    MaterialConfirmation.objects.select_for_update()
                    .select_related("material")
                    .filter(
                        public_id=confirmation_id,
                        organization_id=actor.organization_id,
                    )
                    .exclude(decision=MaterialConfirmationDecision.PENDING)
                    .first()
                )
                if confirmation is None:
                    return False
                self._require_may_repair(confirmation)

                todo = (
                    Todo.objects.select_for_update()
                    .filter(
                        organization_id=confirmation.organization_id,
                        dedup_key=confirmation_todo_dedup_key(confirmation.public_id),
                        status=TodoStatus.OPEN,
                    )
                    .order_by("pk")
                    .first()
                )
                if todo is None:
                    # Nothing is stranded: either it never was, or the repair that
                    # got here first already settled it.
                    return False
                if self._settlement_still_in_flight(confirmation.public_id):
                    # An undelivered settlement will converge on its own; a second
                    # event would only duplicate the work.
                    return False

                event = register_outbox_event(
                    OutboxMessage(
                        event_type="material_confirmation.decided",
                        aggregate_type="material_confirmation",
                        aggregate_id=confirmation.public_id,
                        payload={
                            "confirmation_public_id": str(confirmation.public_id),
                            "material_public_id": str(confirmation.material.public_id),
                            "organization_id": confirmation.organization_id,
                            "decision": confirmation.decision,
                            # The confirmer stays the person who settles the ask;
                            # the operator running the repair is only in the audit.
                            "actor_user_id": confirmation.confirmer_id,
                            "assignee_id": confirmation.confirmer_id,
                            "todo_dedup_key": confirmation_todo_dedup_key(confirmation.public_id),
                            "reissue_reason": REISSUE_REASON,
                        },
                        occurred_at=self.context.occurred_at or timezone.now(),
                    )
                )
                # The unique key decides whether this repair exists, so a loser
                # writes neither an audit record nor a dispatch.
                MaterialConfirmationSettlementRepair.objects.create(
                    organization_id=confirmation.organization_id,
                    confirmation=confirmation,
                    todo_public_id=todo.public_id,
                    reissued_event_id=event.event_id,
                    reason=REISSUE_REASON,
                )
                self._append_repair_audit(confirmation, todo)
                schedule_local_dispatch_after_commit(event)
        except IntegrityError:
            return False
        return True

    def _settlement_still_in_flight(self, confirmation_public_id: UUID) -> bool:
        return OutboxEvent.objects.filter(
            event_type="material_confirmation.decided",
            aggregate_id=confirmation_public_id,
            status__in=[OutboxStatus.PENDING, OutboxStatus.PROCESSING],
        ).exists()

    def _require_may_repair(self, confirmation: MaterialConfirmation) -> None:
        material = confirmation.material
        decision = authorize(
            subject_for(self.context.actor),
            action="product_material.manage",
            resource=ResourceDescriptor(
                resource_type="product_material",
                public_id=material.public_id,
                organization_id=material.organization_id,
                sensitivity_level=material.sensitivity_level,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

    def _append_repair_audit(self, confirmation: MaterialConfirmation, todo: Todo) -> None:
        append_event(
            AuditRecord(
                actor=self.context.actor,
                action_code="product_material.confirmation_settle_reissue",
                resource_type="material_confirmation",
                resource_public_id=confirmation.public_id,
                result=AuditResult.SUCCESS,
                trace_id=self.context.trace_id,
                occurred_at=self.context.occurred_at or timezone.now(),
                acting_roles_snapshot=acting_roles_snapshot(self.context.actor),
                after_summary={
                    "decision": confirmation.decision,
                    "todo_public_id": str(todo.public_id),
                    "todo_dedup_key": todo.dedup_key,
                    "reissue_reason": REISSUE_REASON,
                },
            )
        )


def _confirmation_id_in(dedup_key: str) -> UUID | None:
    try:
        return UUID(dedup_key.removeprefix(_TODO_DEDUP_PREFIX))
    except ValueError:
        return None


def _ordered(confirmation_public_ids: Iterable[UUID]) -> list[UUID]:
    """Stable order across processes so two repairs queue rather than deadlock."""

    return sorted(dict.fromkeys(confirmation_public_ids), key=str)
