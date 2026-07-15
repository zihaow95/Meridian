"""Stage handling mode requests and confirmations."""

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
from apps.projects.errors import InvalidStageHandlingRequest
from apps.projects.models import (
    ExecutionException,
    ExecutionExceptionStatus,
    ProjectStage,
    StageHandlingMode,
)

_REQUESTABLE_MODES = frozenset(
    {
        StageHandlingMode.REUSE,
        StageHandlingMode.SIMPLIFY,
        StageHandlingMode.EXEMPT,
        StageHandlingMode.PARALLEL,
    }
)


@dataclass
class RequestStageHandlingMode:
    context: CommandContext
    stage_public_id: UUID
    requested_mode: str
    rationale: str

    def execute(self) -> ExecutionException:
        actor = self.context.actor
        if self.requested_mode not in _REQUESTABLE_MODES:
            raise InvalidStageHandlingRequest()
        with transaction.atomic():
            stage = (
                ProjectStage.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.stage_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if stage is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="stage_handling.request",
                resource=ResourceDescriptor(
                    resource_type="project_stage",
                    public_id=stage.public_id,
                    organization_id=stage.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            if stage.project.leader_id != actor.id:
                raise PermissionDeniedError()

            exception = ExecutionException.objects.create(
                organization=stage.organization,
                project=stage.project,
                stage=stage,
                exception_type=self.requested_mode,
                previous_mode=stage.handling_mode,
                requested_mode=self.requested_mode,
                rationale=self.rationale,
                evidence_summary={},
                requested_by=actor,
                status=ExecutionExceptionStatus.PENDING,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="stage_handling.request",
                    resource_type="project_stage",
                    resource_public_id=stage.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "exception_public_id": str(exception.public_id),
                        "requested_mode": self.requested_mode,
                    },
                )
            )
            return exception


@dataclass
class ConfirmExecutionException:
    context: CommandContext
    exception_public_id: UUID

    def execute(self) -> ExecutionException:
        actor = self.context.actor
        with transaction.atomic():
            exception = (
                ExecutionException.objects.select_for_update()
                .select_related("stage", "project")
                .filter(
                    public_id=self.exception_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if exception is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="stage_handling.confirm",
                resource=ResourceDescriptor(
                    resource_type="project_stage",
                    public_id=exception.stage.public_id,
                    organization_id=exception.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            if exception.status != ExecutionExceptionStatus.PENDING:
                raise InvalidStageHandlingRequest(message="Exception is not pending.")

            stage = exception.stage
            stage.handling_mode = exception.requested_mode
            stage.exception = exception
            stage.save(update_fields=["handling_mode", "exception", "updated_at"])
            exception.status = ExecutionExceptionStatus.CONFIRMED
            exception.confirmed_by = actor
            exception.confirmed_at = self.context.occurred_at
            exception.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="stage_handling.confirm",
                    resource_type="project_stage",
                    resource_public_id=stage.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "handling_mode": stage.handling_mode,
                        "exception_public_id": str(exception.public_id),
                    },
                )
            )
            return exception
