"""Repair confirmation todos an earlier build settled into thin air.

A build that settled decisions inside the deciding transaction could record a
consumer receipt for `material_confirmation.decided` while the request's own todo
was still unprojected. The settlement closed nothing, and the receipt now blocks a
replay: the material reads APPROVED while its confirmation todo stays OPEN.

Receipts and the events they describe are history and are kept. The repair is a new
event on the same confirmation, which earns its own receipt and is validated by the
same consumer as any other settlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
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
from apps.products.models import MaterialConfirmation, MaterialConfirmationDecision
from apps.products.services.material_confirmations import confirmation_todo_dedup_key

REISSUE_REASON = "SETTLEMENT_RECEIPT_WITHOUT_TODO"
_TODO_DEDUP_PREFIX = "material_confirmation:"


@dataclass(frozen=True)
class ReissueSettlementForDecidedConfirmations:
    """Re-emit a precise settlement for every decided confirmation left open."""

    context: CommandContext

    def execute(self) -> list[UUID]:
        actor = self.context.actor
        reissued: list[UUID] = []
        with transaction.atomic():
            for todo in self._open_confirmation_todos(actor.organization_id):
                confirmation = self._decided_confirmation_for(todo)
                if confirmation is None:
                    continue
                if self._settlement_still_in_flight(confirmation.public_id):
                    # An undelivered settlement will converge on its own; a second
                    # event would only duplicate the work.
                    continue
                self._require_may_repair(confirmation)
                self._append_repair_audit(confirmation, todo)
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
                schedule_local_dispatch_after_commit(event)
                reissued.append(confirmation.public_id)
        return reissued

    def _open_confirmation_todos(self, organization_id: int) -> list[Todo]:
        return list(
            Todo.objects.filter(
                organization_id=organization_id,
                status=TodoStatus.OPEN,
                dedup_key__startswith=_TODO_DEDUP_PREFIX,
            ).order_by("pk")
        )

    def _decided_confirmation_for(self, todo: Todo) -> MaterialConfirmation | None:
        try:
            confirmation_id = UUID(todo.dedup_key.removeprefix(_TODO_DEDUP_PREFIX))
        except ValueError:
            return None
        return (
            MaterialConfirmation.objects.select_related("material")
            .filter(public_id=confirmation_id, organization_id=todo.organization_id)
            .exclude(decision=MaterialConfirmationDecision.PENDING)
            .first()
        )

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
