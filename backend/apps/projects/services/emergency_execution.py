"""Director-level emergency execution (先行后补)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from apps.projects.errors import PlanChangeNotAllowed
from apps.projects.models import EmergencyExecution, EmergencyExecutionStatus, Project


@dataclass
class CreateEmergencyExecution:
    context: CommandContext
    project_public_id: UUID
    subject_summary: str
    pending_confirmation: str
    due_at: datetime

    def execute(self) -> EmergencyExecution:
        actor = self.context.actor
        with transaction.atomic():
            project = (
                Project.objects.select_for_update()
                .filter(
                    public_id=self.project_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if project is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="emergency_execution.create",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=project.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            roles = acting_roles_snapshot(actor)
            record = EmergencyExecution.objects.create(
                organization=project.organization,
                project=project,
                subject_summary=self.subject_summary,
                pending_confirmation=self.pending_confirmation,
                started_at=self.context.occurred_at,
                due_at=self.due_at,
                initiated_by=actor,
                initiator_roles_snapshot=roles,
                status=EmergencyExecutionStatus.OPEN,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="emergency_execution.create",
                    resource_type="project",
                    resource_public_id=project.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=roles,
                    after_summary={
                        "emergency_public_id": str(record.public_id),
                        "due_at": self.due_at.isoformat(),
                    },
                )
            )
            return record


@dataclass
class CompleteEmergencyExecution:
    context: CommandContext
    emergency_public_id: UUID
    confirmation_summary: str

    def execute(self) -> EmergencyExecution:
        actor = self.context.actor
        with transaction.atomic():
            record = (
                EmergencyExecution.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.emergency_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if record is None:
                raise PermissionDeniedError()
            if record.status == EmergencyExecutionStatus.COMPLETED:
                return record
            if record.status not in (
                EmergencyExecutionStatus.OPEN,
                EmergencyExecutionStatus.OVERDUE,
            ):
                raise PlanChangeNotAllowed(
                    message="Emergency execution cannot be completed in current status."
                )

            decision = authorize(
                subject_for(actor),
                action="emergency_execution.create",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=record.project.public_id,
                    organization_id=record.project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            roles = acting_roles_snapshot(actor)
            record.status = EmergencyExecutionStatus.COMPLETED
            record.completed_at = self.context.occurred_at
            record.save(update_fields=["status", "completed_at", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="emergency_execution.create",
                    resource_type="project",
                    resource_public_id=record.project.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=roles,
                    after_summary={
                        "emergency_public_id": str(record.public_id),
                        "status": record.status,
                        "confirmation_summary": self.confirmation_summary,
                    },
                )
            )
            return record
