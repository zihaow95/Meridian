"""Confirm a migration baseline as CONTINUE or ARCHIVE_ONLY."""

from __future__ import annotations

from dataclasses import dataclass
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
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.errors import (
    MigrationBaselineAlreadyConfirmed,
    MigrationImportFailed,
    ProjectTemplateNotPublished,
)
from apps.projects.models import (
    MigrationBaseline,
    MigrationBaselineStatus,
    MigrationDisposition,
    Project,
    ProjectStage,
    ProjectStageStatus,
    ProjectStatus,
    ProjectType,
    StageHandlingMode,
)
from apps.projects.services.initialize_runtime import PROJECT_EXECUTION_TEMPLATE_CODE
from apps.work_items.models import Task, TaskSourceType, TaskStatus


@dataclass(frozen=True)
class ConfirmMigrationResult:
    baseline: MigrationBaseline
    project: Project | None


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

            existing = MigrationBaseline.objects.filter(
                confirm_idempotency_key=self.idempotency_key
            ).first()
            if existing is not None:
                project = Project.objects.filter(migration_baseline=existing).first()
                return ConfirmMigrationResult(baseline=existing, project=project)

            if baseline.status == MigrationBaselineStatus.CONFIRMED:
                raise MigrationBaselineAlreadyConfirmed()

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
        actor,
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
        remaining = [
            entry for entry in stages_def if int(entry["sequence_no"]) >= current_seq
        ]

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
                    code
                    for code in (entry.get("depends_on") or [])
                    if code in {item["code"] for item in remaining}
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
        project.save(update_fields=["current_stage", "updated_at"])

        # Do not create stage gate instances for skipped historical stages.
        # FIRST_LAUNCH gate for L2 is created only when that stage is reached / active later.
        department = Department.objects.filter(
            organization=baseline.organization,
            status=DepartmentStatus.ACTIVE,
        ).first()
        if department is None:
            department = Department.objects.create(
                organization=baseline.organization,
                department_code="MIG",
                name="Migration Dept",
                status=DepartmentStatus.ACTIVE,
                valid_from=self.context.occurred_at,
            )

        for item in baseline.history_tasks:
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

        # Template tasks for remaining stages only (if any).
        stages_by_code = {stage.stage_code: stage for stage in created_stages}
        for entry in content.get("tasks") or []:
            stage = stages_by_code.get(entry.get("stage_code"))
            if stage is None:
                continue
            dept = Department.objects.filter(
                organization=baseline.organization,
                department_code=entry["responsible_department_code"],
            ).first()
            if dept is None:
                dept = department
            try:
                Task.objects.create(
                    organization=baseline.organization,
                    project=project,
                    stage=stage,
                    task_code=entry["task_code"],
                    name=entry["name"],
                    description=str(entry.get("description") or ""),
                    source_type=TaskSourceType.TEMPLATE,
                    is_core=bool(entry.get("is_core", True)),
                    responsible_department=dept,
                    status=TaskStatus.NOT_STARTED,
                    version_no=1,
                )
            except IntegrityError:
                continue

        return project
