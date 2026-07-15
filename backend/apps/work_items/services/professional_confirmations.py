"""Professional confirmation decisions bound to a revision hash."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.work_items.models import (
    DeliverableRevisionStatus,
    DeliverableStatus,
    ProfessionalConfirmation,
    ProfessionalConfirmationStatus,
)


@dataclass
class DecideProfessionalConfirmation:
    context: CommandContext
    confirmation_public_id: UUID
    decision: str
    comment: str = ""

    def execute(self) -> ProfessionalConfirmation:
        actor = self.context.actor
        if self.decision not in {
            ProfessionalConfirmationStatus.APPROVED,
            ProfessionalConfirmationStatus.RETURNED,
        }:
            raise PermissionDeniedError()

        with transaction.atomic():
            confirmation = (
                ProfessionalConfirmation.objects.select_for_update()
                .select_related("deliverable_revision", "deliverable_revision__deliverable")
                .filter(
                    public_id=self.confirmation_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if confirmation is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="professional_confirmation.decide",
                resource=ResourceDescriptor(
                    resource_type="professional_confirmation",
                    public_id=confirmation.public_id,
                    organization_id=confirmation.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            if confirmation.confirmer_id != actor.id:
                raise PermissionDeniedError()
            if confirmation.status != ProfessionalConfirmationStatus.PENDING:
                raise PermissionDeniedError()

            now = self.context.occurred_at
            confirmation.status = self.decision
            confirmation.comment = self.comment
            confirmation.confirmed_at = now
            confirmation.save(update_fields=["status", "comment", "confirmed_at", "updated_at"])

            revision = confirmation.deliverable_revision
            deliverable = revision.deliverable
            if self.decision == ProfessionalConfirmationStatus.APPROVED:
                revision.status = DeliverableRevisionStatus.CONTROLLED
                deliverable.status = DeliverableStatus.CONFIRMED
            else:
                revision.status = DeliverableRevisionStatus.DRAFT
                deliverable.status = DeliverableStatus.DRAFT
            revision.save(update_fields=["status", "updated_at"])
            deliverable.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="professional_confirmation.decide",
                    resource_type="professional_confirmation",
                    resource_public_id=confirmation.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "decision": confirmation.status,
                        "revision_public_id": str(revision.public_id),
                        "content_hash": revision.content_hash,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="professional_confirmation.decided",
                    aggregate_type="professional_confirmation",
                    aggregate_id=confirmation.public_id,
                    payload={
                        "confirmation_public_id": str(confirmation.public_id),
                        "decision": confirmation.status,
                    },
                    occurred_at=now,
                )
            )
            return confirmation
