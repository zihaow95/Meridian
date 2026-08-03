"""Professional confirmation of one exact file version.

A confirmation is a person's statement about bytes they read. It therefore
names a `DocumentVersion` and its hash, may only be decided by the person it was
addressed to, and dies the moment the material moves to a newer file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.notifications.services.todos import CompleteOpenTodosForSource
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import (
    OutboxMessage,
    register_outbox_event,
    schedule_local_dispatch_after_commit,
)
from apps.products.models import (
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialStatus,
    ProductMaterial,
)

_DECIDABLE = frozenset(
    {MaterialConfirmationDecision.APPROVED, MaterialConfirmationDecision.RETURNED}
)


class MaterialConfirmationRejected(Exception):
    """The confirmation step cannot proceed as asked."""


def _may_confirm(user: User, material: ProductMaterial) -> bool:
    return authorize(
        subject_for(user),
        action="product_material.confirm",
        resource=ResourceDescriptor(
            resource_type="product_material",
            public_id=material.public_id,
            organization_id=material.organization_id,
            sensitivity_level=material.sensitivity_level,
            metadata={"material_type_code": material.material_type_code},
        ),
        context=AuthorizationContext.current(),
    ).allowed


def supersede_live_confirmations(material: ProductMaterial, *, at: datetime | None = None) -> None:
    """Retire, never delete: the decision stays readable as history."""
    MaterialConfirmation.objects.filter(material=material, live_slot=1).update(
        superseded_at=at or timezone.now(),
        live_slot=None,
        updated_at=timezone.now(),
    )


@dataclass(frozen=True)
class SubmitMaterialConfirmation:
    context: CommandContext
    material_public_id: UUID
    confirmer_public_id: UUID
    comment: str = ""

    def execute(self) -> MaterialConfirmation:
        actor = self.context.actor
        with transaction.atomic():
            material = (
                ProductMaterial.objects.select_for_update()
                .select_related("document_version__file_object")
                .filter(
                    public_id=self.material_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if material is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
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

            if material.current_slot is None:
                raise MaterialConfirmationRejected(
                    "Only the current material version can be sent for confirmation."
                )

            confirmer = User.objects.filter(
                public_id=self.confirmer_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if confirmer is None:
                raise MaterialConfirmationRejected("The nominated confirmer is not available.")
            if not _may_confirm(confirmer, material):
                raise MaterialConfirmationRejected(
                    "The nominated confirmer is not authorized to confirm this material."
                )

            if MaterialConfirmation.objects.filter(material=material, live_slot=1).exists():
                raise MaterialConfirmationRejected(
                    "This material already has a confirmation in flight."
                )

            confirmation = MaterialConfirmation.objects.create(
                organization_id=material.organization_id,
                material=material,
                document_version=material.document_version,
                content_hash=material.document_version.file_object.sha256,
                requested_by=actor,
                requested_at=timezone.now(),
                confirmer=confirmer,
                comment=self.comment,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_material.confirmation_request",
                    resource_type="material_confirmation",
                    resource_public_id=confirmation.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=timezone.now(),
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "material_public_id": str(material.public_id),
                        "material_type_code": material.material_type_code,
                        "confirmer_public_id": str(confirmer.public_id),
                        "content_hash": confirmation.content_hash,
                    },
                )
            )
            title = f"Confirm material {material.material_type_code}"
            dedup_key = f"material_confirmation:{confirmation.public_id}"
            outbox_event = register_outbox_event(
                OutboxMessage(
                    event_type="todo.requested",
                    aggregate_type="material_confirmation",
                    aggregate_id=confirmation.public_id,
                    payload={
                        "assignee_id": confirmer.id,
                        "organization_id": material.organization_id,
                        "todo_type": "material_confirmation",
                        # Authorize the confirmer against the material they must review.
                        "source_type": "product_material",
                        "source_id": str(material.public_id),
                        "action_code": "product_material.confirm",
                        "dedup_key": dedup_key,
                        "deep_link": f"/products?confirm={confirmation.public_id}",
                        "title": title,
                        "template_code": "todo.created",
                        "level": "IMPORTANT",
                    },
                    occurred_at=self.context.occurred_at or timezone.now(),
                )
            )
            # After commit only: notification/todo failure must not unwind confirmation.
            schedule_local_dispatch_after_commit(outbox_event)
        return confirmation


@dataclass(frozen=True)
class DecideMaterialConfirmation:
    context: CommandContext
    confirmation_public_id: UUID
    decision: str
    comment: str = ""

    def execute(self) -> MaterialConfirmation:
        actor = self.context.actor
        if self.decision not in _DECIDABLE:
            raise MaterialConfirmationRejected(f"{self.decision} is not a confirmation decision.")

        with transaction.atomic():
            confirmation = (
                MaterialConfirmation.objects.select_for_update()
                .select_related("material__document_version__file_object")
                .filter(
                    public_id=self.confirmation_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if confirmation is None:
                raise PermissionDeniedError()

            material = confirmation.material
            # Nomination narrows; it never widens. The deciding user must be the
            # person the request was addressed to *and* still hold the action.
            if confirmation.confirmer_id != actor.id or not _may_confirm(actor, material):
                raise PermissionDeniedError()

            if confirmation.decision != MaterialConfirmationDecision.PENDING:
                raise MaterialConfirmationRejected("This confirmation was already decided.")
            if confirmation.superseded_at is not None:
                raise MaterialConfirmationRejected(
                    "The file moved on since this confirmation was requested."
                )
            if confirmation.content_hash != material.document_version.file_object.sha256:
                raise MaterialConfirmationRejected(
                    "The stored bytes no longer match what was sent for confirmation."
                )

            approved = self.decision == MaterialConfirmationDecision.APPROVED
            confirmation.decision = self.decision
            confirmation.decided_at = timezone.now()
            confirmation.comment = self.comment
            confirmation.live_slot = 1 if approved else None
            confirmation.save(
                update_fields=["decision", "decided_at", "comment", "live_slot", "updated_at"]
            )

            material.material_status = MaterialStatus.APPROVED if approved else MaterialStatus.DRAFT
            material.save(update_fields=["material_status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_material.confirm",
                    resource_type="material_confirmation",
                    resource_public_id=confirmation.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=timezone.now(),
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary=self._audit_summary(confirmation, material),
                )
            )
            CompleteOpenTodosForSource(
                organization_id=confirmation.organization_id,
                source_type="product_material",
                source_id=material.public_id,
                actor=actor,
                trace_id=self.context.trace_id,
            ).execute()
        return confirmation

    def _audit_summary(
        self, confirmation: MaterialConfirmation, material: ProductMaterial
    ) -> dict[str, Any]:
        return {
            "decision": confirmation.decision,
            "material_public_id": str(material.public_id),
            "material_type_code": material.material_type_code,
            "document_version_public_id": str(material.document_version.public_id),
            "content_hash": confirmation.content_hash,
        }
