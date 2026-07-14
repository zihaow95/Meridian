"""Deliverable void/exempt and immutable revisions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.models import DocumentVersion, StorageStatus, VersionStatus
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.work_items.errors import CoreDeliverableProtected, InactiveFileObject
from apps.work_items.models import (
    Deliverable,
    DeliverableRevision,
    DeliverableRevisionStatus,
    DeliverableStatus,
    DeliverableTier,
    ProfessionalConfirmation,
    ProfessionalConfirmationStatus,
)


def _authorize(*, actor: User, action: str, resource_type: str, resource) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type=resource_type,
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


@dataclass
class VoidDeliverable:
    context: CommandContext
    deliverable_public_id: UUID

    def execute(self) -> Deliverable:
        actor = self.context.actor
        with transaction.atomic():
            deliverable = (
                Deliverable.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.deliverable_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if deliverable is None:
                raise PermissionDeniedError()
            _authorize(
                actor=actor,
                action="plan.edit",
                resource_type="project",
                resource=deliverable.project,
            )
            if deliverable.tier == DeliverableTier.CORE_REQUIRED:
                raise CoreDeliverableProtected()
            deliverable.status = DeliverableStatus.VOIDED
            deliverable.save(update_fields=["status", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="plan.edit",
                    resource_type="deliverable",
                    resource_public_id=deliverable.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"status": deliverable.status},
                )
            )
            return deliverable


@dataclass
class ExemptDeliverable:
    context: CommandContext
    deliverable_public_id: UUID
    reason: str

    def execute(self) -> Deliverable:
        actor = self.context.actor
        with transaction.atomic():
            deliverable = (
                Deliverable.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.deliverable_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if deliverable is None:
                raise PermissionDeniedError()
            _authorize(
                actor=actor,
                action="plan.edit",
                resource_type="project",
                resource=deliverable.project,
            )
            if deliverable.tier != DeliverableTier.CORE_REQUIRED:
                raise CoreDeliverableProtected(
                    message="Only core required deliverables use exemption."
                )
            deliverable.status = DeliverableStatus.EXEMPTED
            deliverable.exemption_reason = self.reason
            deliverable.save(update_fields=["status", "exemption_reason", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="plan.edit",
                    resource_type="deliverable",
                    resource_public_id=deliverable.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "status": deliverable.status,
                        "reason": self.reason,
                    },
                )
            )
            return deliverable


@dataclass
class CreateDeliverableRevision:
    context: CommandContext
    deliverable_public_id: UUID
    document_version_public_id: UUID

    def execute(self) -> DeliverableRevision:
        actor = self.context.actor
        with transaction.atomic():
            deliverable = (
                Deliverable.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.deliverable_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if deliverable is None:
                raise PermissionDeniedError()
            _authorize(
                actor=actor,
                action="deliverable.create",
                resource_type="deliverable",
                resource=deliverable,
            )
            document_version = (
                DocumentVersion.objects.select_related("file_object")
                .filter(
                    public_id=self.document_version_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if document_version is None:
                raise PermissionDeniedError()
            if document_version.file_object.storage_status != StorageStatus.ACTIVE:
                raise InactiveFileObject()

            next_number = (
                DeliverableRevision.objects.filter(deliverable=deliverable).aggregate(
                    Max("revision_number")
                )["revision_number__max"]
                or 0
            ) + 1

            ProfessionalConfirmation.objects.filter(
                deliverable_revision__deliverable=deliverable,
                status__in=[
                    ProfessionalConfirmationStatus.PENDING,
                    ProfessionalConfirmationStatus.APPROVED,
                    ProfessionalConfirmationStatus.RETURNED,
                ],
            ).update(status=ProfessionalConfirmationStatus.SUPERSEDED)

            DeliverableRevision.objects.filter(
                deliverable=deliverable,
                status__in=[
                    DeliverableRevisionStatus.DRAFT,
                    DeliverableRevisionStatus.SUBMITTED,
                    DeliverableRevisionStatus.LOCKED,
                    DeliverableRevisionStatus.CONTROLLED,
                ],
            ).exclude(status=DeliverableRevisionStatus.SUPERSEDED).update(
                status=DeliverableRevisionStatus.SUPERSEDED
            )

            revision = DeliverableRevision.objects.create(
                organization=deliverable.organization,
                deliverable=deliverable,
                revision_number=next_number,
                document_version=document_version,
                status=DeliverableRevisionStatus.DRAFT,
                content_hash=document_version.file_object.sha256,
            )
            deliverable.current_revision = revision
            deliverable.status = DeliverableStatus.DRAFT
            deliverable.save(update_fields=["current_revision", "status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="deliverable.create",
                    resource_type="deliverable",
                    resource_public_id=deliverable.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "revision_public_id": str(revision.public_id),
                        "revision_number": revision.revision_number,
                        "content_hash": revision.content_hash,
                    },
                )
            )
            return revision


@dataclass
class SubmitRevisionForConfirmation:
    context: CommandContext
    revision_public_id: UUID
    confirmer_public_id: UUID

    def execute(self) -> DeliverableRevision:
        actor = self.context.actor
        with transaction.atomic():
            revision = (
                DeliverableRevision.objects.select_for_update()
                .select_related("deliverable", "deliverable__project", "document_version")
                .filter(
                    public_id=self.revision_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if revision is None:
                raise PermissionDeniedError()
            _authorize(
                actor=actor,
                action="revision.submit",
                resource_type="deliverable_revision",
                resource=revision,
            )
            confirmer = User.objects.filter(
                public_id=self.confirmer_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if confirmer is None:
                raise PermissionDeniedError()

            now = self.context.occurred_at
            revision.status = DeliverableRevisionStatus.LOCKED
            revision.submitted_by = actor
            revision.submitted_at = now
            revision.locked_at = now
            revision.save(
                update_fields=[
                    "status",
                    "submitted_by",
                    "submitted_at",
                    "locked_at",
                    "updated_at",
                ]
            )
            document_version = revision.document_version
            if document_version.status == VersionStatus.DRAFT:
                document_version.status = VersionStatus.LOCKED
                document_version.locked_at = now
                document_version.save(update_fields=["status", "locked_at"])

            deliverable = revision.deliverable
            deliverable.status = DeliverableStatus.SUBMITTED
            deliverable.save(update_fields=["status", "updated_at"])

            ProfessionalConfirmation.objects.create(
                organization=revision.organization,
                deliverable_revision=revision,
                confirmer=confirmer,
                assigned_by=actor,
                status=ProfessionalConfirmationStatus.PENDING,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="revision.submit",
                    resource_type="deliverable_revision",
                    resource_public_id=revision.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "confirmer_public_id": str(confirmer.public_id),
                        "content_hash": revision.content_hash,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="deliverable.revision_submitted",
                    aggregate_type="deliverable_revision",
                    aggregate_id=revision.public_id,
                    payload={"revision_public_id": str(revision.public_id)},
                    occurred_at=now,
                )
            )
            return revision
