"""Confirm a migration baseline as CONTINUE or ARCHIVE_ONLY."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.configuration.models import ConfigurationStatus, ConfigurationVersion
from apps.configuration.services import CreateSnapshot
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.errors import (
    MigrationBaselineAlreadyConfirmed,
    MigrationImportFailed,
    ProjectTemplateInvalid,
    ProjectTemplateNotPublished,
)
from apps.projects.models import (
    MigrationBaseline,
    MigrationBaselineStatus,
    MigrationDisposition,
    Project,
    ProjectRole,
    ProjectStage,
    ProjectStageStatus,
    ProjectStatus,
    ProjectType,
    StageHandlingMode,
)
from apps.projects.services.appoint_member import AppointProjectMember
from apps.projects.services.initialize_runtime import (
    PROJECT_EXECUTION_TEMPLATE_CODE,
    require_template_departments,
)
from apps.stage_gates.services.open_execution_gates import open_execution_gates_for_stages
from apps.work_items.models import (
    Deliverable,
    DeliverableStatus,
    DeliverableTier,
    Task,
    TaskSourceType,
    TaskStatus,
)
from apps.work_items.services.materialize_template import (
    materialize_template_deliverables,
    materialize_template_tasks,
)


@dataclass(frozen=True)
class ConfirmMigrationResult:
    baseline: MigrationBaseline
    project: Project | None


def _resolve_migration_leader(*, baseline: MigrationBaseline, actor: User) -> User:
    plan = baseline.plan_summary or {}
    leader_pid = plan.get("leader_public_id")
    if leader_pid:
        matched = User.objects.filter(
            public_id=leader_pid,
            organization_id=baseline.organization_id,
        ).first()
        if matched is not None:
            return matched
    if baseline.leader_display_name:
        matched = User.objects.filter(
            organization_id=baseline.organization_id,
            display_name=baseline.leader_display_name,
        ).first()
        if matched is not None:
            return matched
    return actor


def _materialize_history_file(
    *,
    project: Project,
    stage: ProjectStage,
    item: dict[str, Any],
    actor: User,
) -> Deliverable:
    del actor
    filename = str(item.get("filename") or "migrated-file")
    code = f"MIG-FILE-{uuid4().hex[:10]}"
    return Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        deliverable_code=code,
        name=filename,
        tier=DeliverableTier.PROJECT_CUSTOM,
        status=DeliverableStatus.CONTROLLED,
        requires_professional_confirmation=False,
        exemption_reason=str(item.get("source_note") or "Migrated history file"),
    )


def _filter_content_for_stages(content: dict[str, Any], stage_codes: set[str]) -> dict[str, Any]:
    filtered = dict(content)
    filtered["tasks"] = [
        entry
        for entry in (content.get("tasks") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    remaining_task_codes = {str(entry.get("task_code")) for entry in filtered["tasks"]}
    filtered["tasks"] = [
        {
            **entry,
            "depends_on": [
                pred
                for pred in (entry.get("depends_on") or [])
                if str(pred) in remaining_task_codes
            ],
        }
        for entry in filtered["tasks"]
    ]
    filtered["deliverables"] = [
        entry
        for entry in (content.get("deliverables") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    filtered["gates"] = [
        entry
        for entry in (content.get("gates") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    return filtered


@dataclass
class ConfirmMigrationBaseline:
    context: CommandContext
    baseline_public_id: UUID
    disposition: str
    idempotency_key: str

    def execute(self) -> ConfirmMigrationResult:
        actor = self.context.actor
        with transaction.atomic():
            baseline = (
                MigrationBaseline.objects.select_for_update()
                .select_related("batch")
                .filter(
                    public_id=self.baseline_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if baseline is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="project_migration.confirm",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=None,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            existing = MigrationBaseline.objects.filter(
                organization_id=actor.organization_id,
                confirm_idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None:
                project = Project.objects.filter(migration_baseline=existing).first()
                return ConfirmMigrationResult(baseline=existing, project=project)

            if baseline.status == MigrationBaselineStatus.CONFIRMED:
                raise MigrationBaselineAlreadyConfirmed()

            if self.disposition not in MigrationDisposition.values:
                raise MigrationImportFailed(message=f"Invalid disposition: {self.disposition}")

            baseline.disposition = self.disposition
            baseline.status = MigrationBaselineStatus.CONFIRMED
            baseline.confirmed_by = actor
            baseline.confirmed_at = self.context.occurred_at
            baseline.confirm_idempotency_key = self.idempotency_key
            baseline.save(
                update_fields=[
                    "disposition",
                    "status",
                    "confirmed_by",
                    "confirmed_at",
                    "confirm_idempotency_key",
                    "updated_at",
                ]
            )

            project = None
            if self.disposition == MigrationDisposition.CONTINUE:
                project = self._materialize_continued_project(baseline=baseline, actor=actor)

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="project_migration.confirm",
                    resource_type="project",
                    resource_public_id=project.public_id if project else baseline.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "baseline_public_id": str(baseline.public_id),
                        "disposition": baseline.disposition,
                        "project_public_id": str(project.public_id) if project else None,
                        "history_files": list(baseline.history_files or []),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="project_migration.baseline_confirmed",
                    aggregate_type="migration_baseline",
                    aggregate_id=baseline.public_id,
                    payload={
                        "disposition": baseline.disposition,
                        "project_public_id": str(project.public_id) if project else None,
                    },
                    occurred_at=self.context.occurred_at,
                )
            )
            return ConfirmMigrationResult(baseline=baseline, project=project)

    def _materialize_continued_project(
        self,
        *,
        baseline: MigrationBaseline,
        actor: User,
    ) -> Project:
        template = (
            ConfigurationVersion.objects.filter(
                organization_id=baseline.organization_id,
                definition__definition_code=PROJECT_EXECUTION_TEMPLATE_CODE,
                status=ConfigurationStatus.PUBLISHED,
            )
            .select_related("definition")
            .order_by("-version_number")
            .first()
        )
        if template is None:
            raise ProjectTemplateNotPublished()

        snapshot = CreateSnapshot(
            version=template,
            reference_type="project_migration",
            reference_id=baseline.public_id,
            actor=actor,
            context=self.context,
        ).execute()

        content = snapshot.content_copy
        stages_def = list(content.get("stages") or [])
        by_code = {entry["code"]: entry for entry in stages_def}
        if baseline.current_stage_code not in by_code:
            raise MigrationImportFailed(
                message=f"Unknown current stage: {baseline.current_stage_code}"
            )
        current_seq = int(by_code[baseline.current_stage_code]["sequence_no"])
        remaining = [entry for entry in stages_def if int(entry["sequence_no"]) >= current_seq]
        remaining_codes = {entry["code"] for entry in remaining}
        filtered_content = _filter_content_for_stages(content, remaining_codes)

        project = Project.objects.create(
            organization=baseline.organization,
            business_no=f"MIG-{baseline.external_project_id}"[:32],
            name=baseline.name,
            project_type=ProjectType.NEW_PRODUCT,
            status=ProjectStatus.ACTIVE,
            candidate=None,
            leader=actor,
            template_snapshot=snapshot,
            migration_baseline=baseline,
            idempotency_key=f"migration:{baseline.public_id}",
            actual_start_at=self.context.occurred_at,
        )

        created_stages: list[ProjectStage] = []
        for entry in remaining:
            gate = entry.get("gate") or {}
            stage = ProjectStage.objects.create(
                organization=baseline.organization,
                project=project,
                stage_code=entry["code"],
                name=entry["name"],
                sequence_no=int(entry["sequence_no"]),
                status=(
                    ProjectStageStatus.ACTIVE
                    if entry["code"] == baseline.current_stage_code
                    else ProjectStageStatus.NOT_STARTED
                ),
                handling_mode=StageHandlingMode.EXECUTE,
                gate_code=str(gate.get("gate_code") or ""),
                gate_type=str(gate.get("gate_type") or ""),
                depends_on=[
                    code for code in (entry.get("depends_on") or []) if code in remaining_codes
                ],
                actual_start_at=(
                    self.context.occurred_at
                    if entry["code"] == baseline.current_stage_code
                    else None
                ),
            )
            created_stages.append(stage)

        current = next(
            stage for stage in created_stages if stage.stage_code == baseline.current_stage_code
        )
        project.current_stage = current
        planned_end = (baseline.plan_summary or {}).get("planned_end_at")
        if planned_end:
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(str(planned_end))
            if parsed is not None:
                current.planned_end_at = parsed
                current.save(update_fields=["planned_end_at", "updated_at"])
                project.planned_end_at = parsed
        project.save(update_fields=["current_stage", "planned_end_at", "updated_at"])

        try:
            require_template_departments(baseline.organization_id)
        except ProjectTemplateInvalid as exc:
            raise MigrationImportFailed(message=str(exc)) from exc

        department = Department.objects.filter(
            organization=baseline.organization,
            department_code="PRODUCT",
            status=DepartmentStatus.ACTIVE,
        ).first()
        if department is None:
            raise MigrationImportFailed(message="PRODUCT department is required for migration.")

        leader = _resolve_migration_leader(baseline=baseline, actor=actor)
        project.leader = leader
        project.save(update_fields=["leader", "updated_at"])

        for item in baseline.history_tasks:
            try:
                Task.objects.create(
                    organization=baseline.organization,
                    project=project,
                    stage=current,
                    task_code=str(item.get("task_code") or f"HIST-{uuid4().hex[:8]}"),
                    name=str(item.get("name") or "Migrated history task"),
                    description=f"Migrated from stage {item.get('stage_code', '')}",
                    source_type=TaskSourceType.MIGRATED_HISTORY,
                    is_core=False,
                    responsible_department=department,
                    status=TaskStatus.COMPLETED,
                    version_no=1,
                )
            except IntegrityError as exc:
                raise MigrationImportFailed(
                    message=f"Failed to materialize history task: {item.get('task_code')}"
                ) from exc

        for item in baseline.history_files or []:
            _materialize_history_file(
                project=project,
                stage=current,
                item=item if isinstance(item, dict) else {"filename": str(item)},
                actor=actor,
            )

        stages_by_code = {stage.stage_code: stage for stage in created_stages}
        materialize_template_tasks(
            project=project,
            stages_by_code=stages_by_code,
            content=filtered_content,
            default_department=department,
        )
        materialize_template_deliverables(
            project=project,
            stages_by_code=stages_by_code,
            content=filtered_content,
        )
        open_execution_gates_for_stages(
            project=project,
            stages=created_stages,
            content=filtered_content,
            ready_stage_codes={baseline.current_stage_code},
        )

        AppointProjectMember(
            context=self.context,
            project_public_id=project.public_id,
            user_public_id=leader.public_id,
            project_role=ProjectRole.LEADER,
        ).execute()

        for member in (baseline.plan_summary or {}).get("members") or []:
            member_id = member.get("user_public_id") if isinstance(member, dict) else None
            role = (
                str(member.get("project_role") or ProjectRole.MEMBER)
                if isinstance(member, dict)
                else ProjectRole.MEMBER
            )
            if not member_id:
                continue
            AppointProjectMember(
                context=self.context,
                project_public_id=project.public_id,
                user_public_id=UUID(str(member_id)),
                project_role=role if role in ProjectRole.values else ProjectRole.MEMBER,
            ).execute()

        return project
