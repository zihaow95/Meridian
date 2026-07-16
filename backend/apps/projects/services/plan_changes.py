"""Plan change commands with minor auto-apply and important confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.errors import PlanChangeNotAllowed
from apps.projects.models import (
    PlanChange,
    PlanChangeStatus,
    PlanChangeType,
    Project,
    ProjectStage,
)


def _authorize_project(*, actor: User, project: Project, action: str) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="project",
            public_id=project.public_id,
            organization_id=project.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _apply_stage_field(stage: ProjectStage, field_name: str, after_value: str) -> None:
    if field_name != "planned_end_at":
        raise PlanChangeNotAllowed(message=f"Unsupported field: {field_name}")
    parsed = parse_datetime(after_value)
    if parsed is None:
        raise PlanChangeNotAllowed(message="Invalid planned_end_at value.")
    if timezone_is_naive(parsed):
        from django.utils import timezone as dj_tz

        parsed = dj_tz.make_aware(parsed, UTC)
    stage.planned_end_at = parsed
    stage.save(update_fields=["planned_end_at", "updated_at"])


def timezone_is_naive(value: datetime) -> bool:
    return value.tzinfo is None or value.tzinfo.utcoffset(value) is None


def _is_resource_field(field_name: str) -> bool:
    return field_name in {"headcount", "budget"} or field_name.startswith("resource_")


def _infer_change_type(
    *,
    field_name: str,
    before_value: str,
    after_value: str,
) -> str:
    """Classify severity from real field change; never trust client type for MINOR."""

    if _is_resource_field(field_name):
        return PlanChangeType.IMPORTANT
    if field_name == "planned_end_at":
        if before_value != after_value:
            return PlanChangeType.IMPORTANT
        return PlanChangeType.MINOR
    if before_value != after_value:
        return PlanChangeType.IMPORTANT
    return PlanChangeType.MINOR


def _current_stage_field_value(stage: ProjectStage, field_name: str) -> str:
    if field_name != "planned_end_at":
        raise PlanChangeNotAllowed(message=f"Unsupported field: {field_name}")
    if stage.planned_end_at is None:
        return ""
    return stage.planned_end_at.isoformat()


@dataclass
class ApplyPlanChange:
    context: CommandContext
    project_public_id: UUID
    change_type: str
    target_type: str
    target_public_id: UUID
    field_name: str
    before_value: str
    after_value: str
    impact_summary: str

    def execute(self) -> PlanChange:
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

            if project.leader_id != actor.id:
                raise PermissionDeniedError()

            if self.target_type != "project_stage":
                raise PlanChangeNotAllowed(message="Unsupported target type.")
            stage = (
                ProjectStage.objects.select_for_update()
                .filter(
                    public_id=self.target_public_id,
                    project=project,
                )
                .first()
            )
            if stage is None:
                raise PlanChangeNotAllowed(message="Target stage not found.")

            actual_before = _current_stage_field_value(stage, self.field_name)
            resolved_type = _infer_change_type(
                field_name=self.field_name,
                before_value=actual_before,
                after_value=self.after_value,
            )
            if self.change_type == PlanChangeType.RESOURCE_ESCALATION:
                resolved_type = PlanChangeType.RESOURCE_ESCALATION
            action = (
                "plan_change.apply_minor" if resolved_type == PlanChangeType.MINOR else "plan.edit"
            )
            _authorize_project(actor=actor, project=project, action=action)

            change = PlanChange.objects.create(
                organization=project.organization,
                project=project,
                change_type=resolved_type,
                target_type=self.target_type,
                target_public_id=self.target_public_id,
                field_name=self.field_name,
                before_value=actual_before,
                after_value=self.after_value,
                impact_summary=self.impact_summary,
                requested_by=actor,
                status=(
                    PlanChangeStatus.APPLIED
                    if resolved_type == PlanChangeType.MINOR
                    else PlanChangeStatus.PENDING_CONFIRMATION
                ),
            )
            if resolved_type == PlanChangeType.MINOR:
                _apply_stage_field(stage, self.field_name, self.after_value)
                change.confirmed_by = actor
                change.confirmed_at = self.context.occurred_at
                change.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code=action,
                    resource_type="project",
                    resource_public_id=project.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "change_public_id": str(change.public_id),
                        "status": change.status,
                        "change_type": change.change_type,
                    },
                )
            )
            return change

    def _apply_target(self, *, project: Project, change: PlanChange) -> None:
        if change.target_type != "project_stage":
            raise PlanChangeNotAllowed(message="Unsupported target type.")
        stage = (
            ProjectStage.objects.select_for_update()
            .filter(
                public_id=change.target_public_id,
                project=project,
            )
            .first()
        )
        if stage is None:
            raise PlanChangeNotAllowed(message="Target stage not found.")
        _apply_stage_field(stage, change.field_name, change.after_value)


@dataclass
class ConfirmPlanChange:
    context: CommandContext
    change_public_id: UUID

    def execute(self) -> PlanChange:
        actor = self.context.actor
        with transaction.atomic():
            change = (
                PlanChange.objects.select_for_update()
                .select_related("project")
                .filter(
                    public_id=self.change_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if change is None:
                raise PermissionDeniedError()
            _authorize_project(
                actor=actor,
                project=change.project,
                action="plan_change.confirm_important",
            )
            if change.status != PlanChangeStatus.PENDING_CONFIRMATION:
                raise PlanChangeNotAllowed(message="Plan change is not pending.")

            ApplyPlanChange(
                context=self.context,
                project_public_id=change.project.public_id,
                change_type=change.change_type,
                target_type=change.target_type,
                target_public_id=change.target_public_id,
                field_name=change.field_name,
                before_value=change.before_value,
                after_value=change.after_value,
                impact_summary=change.impact_summary,
            )._apply_target(project=change.project, change=change)

            change.status = PlanChangeStatus.CONFIRMED
            change.confirmed_by = actor
            change.confirmed_at = self.context.occurred_at
            change.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="plan_change.confirm_important",
                    resource_type="project",
                    resource_public_id=change.project.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"change_public_id": str(change.public_id)},
                )
            )
            return change
