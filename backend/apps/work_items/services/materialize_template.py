"""Materialize template work items for project runtime (public work_items API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.department import Department
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.projects.errors import ProjectTemplateInvalid
from apps.projects.models import Project, ProjectStage
from apps.work_items.models import (
    Deliverable,
    DeliverableStatus,
    DeliverableTier,
    Task,
    TaskDependency,
    TaskDependencyType,
    TaskSourceType,
    TaskStatus,
)


def materialize_template_tasks(
    *,
    project: Project,
    stages_by_code: dict[str, ProjectStage],
    content: dict[str, Any],
    default_department: Department | None = None,
) -> list[Task]:
    """Expand template tasks into work_items rows (idempotent by project+task_code)."""

    created: dict[str, Task] = {}
    for entry in content.get("tasks") or []:
        task_code = str(entry["task_code"])
        existing = Task.objects.filter(project=project, task_code=task_code).first()
        if existing is not None:
            created[task_code] = existing
            continue
        stage = stages_by_code.get(str(entry["stage_code"]))
        if stage is None:
            raise ProjectTemplateInvalid(
                message=f"Task references unknown stage: {entry.get('stage_code')}"
            )
        department = Department.objects.filter(
            organization=project.organization,
            department_code=str(entry["responsible_department_code"]),
        ).first()
        if department is None:
            department = default_department
        if department is None:
            raise ProjectTemplateInvalid(
                message=(
                    f"Missing department for task template: {entry['responsible_department_code']}"
                )
            )
        created[task_code] = Task.objects.create(
            organization=project.organization,
            project=project,
            stage=stage,
            task_code=task_code,
            name=str(entry["name"]),
            description=str(entry.get("description") or ""),
            source_type=TaskSourceType.TEMPLATE,
            is_core=bool(entry.get("is_core", True)),
            responsible_department=department,
            status=TaskStatus.NOT_STARTED,
            version_no=1,
        )

    for entry in content.get("tasks") or []:
        task = created[str(entry["task_code"])]
        for pred_code in entry.get("depends_on") or []:
            predecessor = created.get(str(pred_code))
            if predecessor is None:
                raise ProjectTemplateInvalid(message=f"Unknown task dependency: {pred_code}")
            TaskDependency.objects.get_or_create(
                organization=project.organization,
                task=task,
                predecessor=predecessor,
                defaults={
                    "dependency_type": entry.get("dependency_type") or TaskDependencyType.HARD,
                },
            )
    return list(created.values())


def materialize_template_deliverables(
    *,
    project: Project,
    stages_by_code: dict[str, ProjectStage],
    content: dict[str, Any],
) -> list[Deliverable]:
    """Expand template deliverables (idempotent by project+deliverable_code)."""

    created: list[Deliverable] = []
    for entry in content.get("deliverables") or []:
        code = str(entry["deliverable_code"])
        existing = Deliverable.objects.filter(project=project, deliverable_code=code).first()
        if existing is not None:
            created.append(existing)
            continue
        stage = stages_by_code.get(str(entry["stage_code"]))
        if stage is None:
            raise ProjectTemplateInvalid(
                message=f"Deliverable references unknown stage: {entry.get('stage_code')}"
            )
        tier = str(entry.get("tier") or DeliverableTier.CORE_REQUIRED)
        created.append(
            Deliverable.objects.create(
                organization=project.organization,
                project=project,
                stage=stage,
                deliverable_code=code,
                name=str(entry["name"]),
                tier=tier,
                status=DeliverableStatus.NOT_STARTED,
                requires_professional_confirmation=bool(
                    entry.get("requires_professional_confirmation", True)
                ),
            )
        )
    return created


@dataclass
class CreateCustomTask:
    context: CommandContext
    project_public_id: UUID
    stage_public_id: UUID
    task_code: str
    name: str
    responsible_department_public_id: UUID
    is_core: bool = False
    description: str = ""

    def execute(self) -> Task:
        actor = self.context.actor
        with transaction.atomic():
            project = (
                Project.objects.select_for_update()
                .filter(public_id=self.project_public_id, organization_id=actor.organization_id)
                .first()
            )
            if project is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="task.create",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=project.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            stage = ProjectStage.objects.filter(
                public_id=self.stage_public_id,
                project=project,
            ).first()
            if stage is None:
                raise ValidationFailedError(message="Stage not found on project.")
            department = Department.objects.filter(
                public_id=self.responsible_department_public_id,
                organization_id=actor.organization_id,
            ).first()
            if department is None:
                raise ValidationFailedError(message="Department not found.")
            if Task.objects.filter(project=project, task_code=self.task_code).exists():
                raise ValidationFailedError(message="Task code already exists.")
            task = Task.objects.create(
                organization=project.organization,
                project=project,
                stage=stage,
                task_code=self.task_code,
                name=self.name,
                description=self.description,
                source_type=TaskSourceType.PROJECT_CUSTOM,
                is_core=self.is_core,
                responsible_department=department,
                status=TaskStatus.NOT_STARTED,
                version_no=1,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="task.create",
                    resource_type="task",
                    resource_public_id=task.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"task_code": task.task_code},
                )
            )
            return task


@dataclass
class CreateCustomDeliverable:
    context: CommandContext
    project_public_id: UUID
    stage_public_id: UUID
    deliverable_code: str
    name: str
    requires_professional_confirmation: bool = True

    def execute(self) -> Deliverable:
        actor = self.context.actor
        with transaction.atomic():
            project = (
                Project.objects.select_for_update()
                .filter(public_id=self.project_public_id, organization_id=actor.organization_id)
                .first()
            )
            if project is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="deliverable.create",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=project.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            stage = ProjectStage.objects.filter(
                public_id=self.stage_public_id,
                project=project,
            ).first()
            if stage is None:
                raise ValidationFailedError(message="Stage not found on project.")
            if Deliverable.objects.filter(
                project=project, deliverable_code=self.deliverable_code
            ).exists():
                raise ValidationFailedError(message="Deliverable code already exists.")
            item = Deliverable.objects.create(
                organization=project.organization,
                project=project,
                stage=stage,
                deliverable_code=self.deliverable_code,
                name=self.name,
                tier=DeliverableTier.PROJECT_CUSTOM,
                status=DeliverableStatus.NOT_STARTED,
                requires_professional_confirmation=self.requires_professional_confirmation,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="deliverable.create",
                    resource_type="deliverable",
                    resource_public_id=item.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"deliverable_code": item.deliverable_code},
                )
            )
            return item
