"""Create and configure pilot batches with frozen participant snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.identity.models.user import User, UserStatus
from apps.pilot.errors import BatchCompletionBlocked, PilotValidationError
from apps.pilot.models import (
    PilotBatch,
    PilotBatchPurpose,
    PilotBatchStatus,
    PilotFeedbackSeverity,
    PilotFeedbackStatus,
    PilotParticipant,
)
from apps.platform.application.command import CommandContext


def _active_role_codes(user: User) -> list[str]:
    now = timezone.now()
    return sorted(
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
        .values_list("role__role_code", flat=True)
    )


@dataclass(frozen=True)
class CreatePilotBatch:
    context: CommandContext
    name: str
    planned_participant_count: int = 8
    planned_duration_days: int = 14
    data_scope_note: str = ""
    feedback_owner_note: str = ""
    known_limits_note: str = ""
    stop_conditions_note: str = ""
    purpose: str = PilotBatchPurpose.INTERNAL_ACCEPTANCE

    def execute(self) -> PilotBatch:
        actor = self.context.actor
        name = self.name.strip()
        if not name:
            raise PilotValidationError(message="name is required.")
        if self.planned_participant_count < 1:
            raise PilotValidationError(message="planned_participant_count must be >= 1.")
        if self.planned_duration_days < 1:
            raise PilotValidationError(message="planned_duration_days must be >= 1.")
        if self.purpose not in PilotBatchPurpose.values:
            raise PilotValidationError(message="purpose is invalid.")
        # Phase 6 must not mark a real business pilot as complete; creating one
        # is allowed only as INTERNAL_ACCEPTANCE for the acceptance path.
        if self.purpose != PilotBatchPurpose.INTERNAL_ACCEPTANCE:
            raise PilotValidationError(
                message="Phase 6 only allows INTERNAL_ACCEPTANCE batches."
            )

        with transaction.atomic():
            batch = PilotBatch.objects.create(
                organization_id=actor.organization_id,
                name=name,
                purpose=self.purpose,
                planned_participant_count=self.planned_participant_count,
                planned_duration_days=self.planned_duration_days,
                data_scope_note=self.data_scope_note.strip(),
                feedback_owner_note=self.feedback_owner_note.strip(),
                known_limits_note=self.known_limits_note.strip(),
                stop_conditions_note=self.stop_conditions_note.strip(),
                created_by=actor,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="pilot.batch.manage",
                    resource_type="pilot.batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    after_summary={"name": batch.name, "status": batch.status},
                    reason="CREATED",
                )
            )
            return batch


@dataclass(frozen=True)
class AddPilotParticipant:
    context: CommandContext
    batch_public_id: UUID
    user_public_id: UUID
    department_snapshot: str = ""

    def execute(self) -> PilotParticipant:
        actor = self.context.actor
        with transaction.atomic():
            batch = (
                PilotBatch.objects.select_for_update()
                .filter(
                    public_id=self.batch_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if batch is None:
                raise PilotValidationError(message="batch was not found.")
            if batch.status != PilotBatchStatus.DRAFT:
                raise PilotValidationError(
                    message="Participants can only be added while the batch is DRAFT."
                )

            user = User.objects.filter(
                public_id=self.user_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if user is None:
                raise PilotValidationError(message="participant user was not found.")

            existing = PilotParticipant.objects.filter(batch=batch, user=user).first()
            if existing is not None:
                return existing

            participant = PilotParticipant.objects.create(
                organization_id=actor.organization_id,
                batch=batch,
                user=user,
                display_name_snapshot=user.display_name,
                employee_no_snapshot=user.employee_no or "",
                department_snapshot=self.department_snapshot.strip(),
                role_codes_snapshot=_active_role_codes(user),
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="pilot.batch.manage",
                    resource_type="pilot.batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    after_summary={
                        "participant_public_id": str(participant.public_id),
                        "user_public_id": str(user.public_id),
                    },
                    reason="PARTICIPANT_ADDED",
                )
            )
            return participant


@dataclass(frozen=True)
class StartPilotBatch:
    """Move DRAFT → OPEN and freeze the editable configuration into a snapshot."""

    context: CommandContext
    batch_public_id: UUID

    def execute(self) -> PilotBatch:
        actor = self.context.actor
        with transaction.atomic():
            batch = (
                PilotBatch.objects.select_for_update()
                .filter(
                    public_id=self.batch_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if batch is None:
                raise PilotValidationError(message="batch was not found.")
            if batch.status == PilotBatchStatus.OPEN:
                return batch
            if batch.status != PilotBatchStatus.DRAFT:
                raise PilotValidationError(message="Only DRAFT batches can be started.")
            if not batch.participants.exists():
                raise PilotValidationError(message="At least one participant is required.")

            snapshot: dict[str, Any] = {
                "planned_participant_count": batch.planned_participant_count,
                "planned_duration_days": batch.planned_duration_days,
                "data_scope_note": batch.data_scope_note,
                "feedback_owner_note": batch.feedback_owner_note,
                "known_limits_note": batch.known_limits_note,
                "stop_conditions_note": batch.stop_conditions_note,
                "participants": [
                    {
                        "user_public_id": str(p.user.public_id),
                        "display_name": p.display_name_snapshot,
                        "employee_no": p.employee_no_snapshot,
                        "department": p.department_snapshot,
                        "role_codes": p.role_codes_snapshot,
                    }
                    for p in batch.participants.select_related("user").order_by("id")
                ],
            }
            now = self.context.occurred_at
            batch.status = PilotBatchStatus.OPEN
            batch.config_snapshot = snapshot
            batch.started_at = now
            batch.version_no += 1
            batch.save(
                update_fields=[
                    "status",
                    "config_snapshot",
                    "started_at",
                    "version_no",
                    "updated_at",
                ]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="pilot.batch.manage",
                    resource_type="pilot.batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    after_summary={"status": batch.status},
                    reason="STARTED",
                )
            )
            return batch


@dataclass(frozen=True)
class CompletePilotBatch:
    """Complete an OPEN internal-acceptance batch when no P0/P1 remain open."""

    context: CommandContext
    batch_public_id: UUID

    def execute(self) -> PilotBatch:
        actor = self.context.actor
        with transaction.atomic():
            batch = (
                PilotBatch.objects.select_for_update()
                .filter(
                    public_id=self.batch_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if batch is None:
                raise PilotValidationError(message="batch was not found.")
            if batch.status == PilotBatchStatus.COMPLETED:
                return batch
            if batch.status != PilotBatchStatus.OPEN:
                raise PilotValidationError(message="Only OPEN batches can be completed.")
            if batch.purpose != PilotBatchPurpose.INTERNAL_ACCEPTANCE:
                raise PilotValidationError(
                    message="Only INTERNAL_ACCEPTANCE batches may be completed in Phase 6."
                )

            blocking = batch.feedback_items.filter(
                severity__in=[PilotFeedbackSeverity.P0, PilotFeedbackSeverity.P1],
            ).exclude(
                status__in=[PilotFeedbackStatus.CLOSED, PilotFeedbackStatus.REJECTED]
            )
            if blocking.exists():
                raise BatchCompletionBlocked()

            now = self.context.occurred_at
            batch.status = PilotBatchStatus.COMPLETED
            batch.completed_at = now
            batch.version_no += 1
            batch.save(
                update_fields=["status", "completed_at", "version_no", "updated_at"]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="pilot.batch.manage",
                    resource_type="pilot.batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    after_summary={"status": batch.status, "purpose": batch.purpose},
                    reason="COMPLETED_INTERNAL_ACCEPTANCE",
                )
            )
            return batch
