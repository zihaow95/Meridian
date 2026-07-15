"""Permission-filtered project workbench queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.identity.models.user import User
from apps.projects.models import Project, ProjectMember, ProjectStage
from apps.projects.queries.projects import serialize_project_detail

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class ProjectSearchPage:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    count: int


def can_access_project(user: User, project: Project) -> bool:
    if project.leader_id == user.id or project.deputy_leader_id == user.id:
        return True
    return ProjectMember.objects.filter(
        project=project,
        user=user,
        active_to__isnull=True,
    ).exists()


def _visible_projects(user: User) -> QuerySet[Project]:
    membership_ids = ProjectMember.objects.filter(
        user=user,
        active_to__isnull=True,
        organization_id=user.organization_id,
    ).values_list("project_id", flat=True)
    return (
        Project.objects.filter(organization_id=user.organization_id)
        .filter(
            Q(leader=user)
            | Q(deputy_leader=user)
            | Q(id__in=membership_ids)
        )
        .select_related(
            "leader",
            "deputy_leader",
            "product_asset",
            "product_draft",
            "candidate",
            "current_stage",
        )
        .order_by("business_no", "public_id")
    )


def search_projects(
    user: User,
    *,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
    status: str | None = None,
) -> ProjectSearchPage:
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)
    qs = _visible_projects(user)
    if status:
        qs = qs.filter(status=status)
    count = qs.count()
    offset = (page - 1) * page_size
    items = [
        {
            "public_id": str(project.public_id),
            "business_no": project.business_no,
            "name": project.name,
            "project_type": project.project_type,
            "status": project.status,
            "leader_public_id": str(project.leader.public_id),
            "current_stage_code": (
                project.current_stage.stage_code if project.current_stage_id else None
            ),
        }
        for project in qs[offset : offset + page_size]
    ]
    return ProjectSearchPage(items=items, page=page, page_size=page_size, count=count)


def get_project_for_user(user: User, public_id: UUID) -> Project | None:
    project = (
        Project.objects.select_related(
            "leader",
            "deputy_leader",
            "product_asset",
            "product_draft",
            "candidate",
            "current_stage",
        )
        .filter(public_id=public_id, organization_id=user.organization_id)
        .first()
    )
    if project is None or not can_access_project(user, project):
        return None
    return project


def serialize_workbench_project(project: Project) -> dict[str, Any]:
    payload = serialize_project_detail(project)
    payload["current_stage_code"] = (
        project.current_stage.stage_code if project.current_stage_id else None
    )
    return payload


def list_project_stages(user: User, project_public_id: UUID) -> list[dict[str, Any]] | None:
    from apps.stage_gates.models import StageGateInstance

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    gates_by_stage = {
        gate.project_stage_id: gate
        for gate in StageGateInstance.objects.filter(project=project, project_stage_id__isnull=False)
    }
    return [
        {
            "public_id": str(stage.public_id),
            "stage_code": stage.stage_code,
            "name": stage.name,
            "sequence_no": stage.sequence_no,
            "status": stage.status,
            "gate_code": stage.gate_code,
            "gate_type": stage.gate_type,
            "handling_mode": stage.handling_mode,
            "planned_end_at": stage.planned_end_at.isoformat() if stage.planned_end_at else None,
            "stage_gate_public_id": (
                str(gates_by_stage[stage.id].public_id) if stage.id in gates_by_stage else None
            ),
        }
        for stage in ProjectStage.objects.filter(project=project).order_by("sequence_no")
    ]


def list_project_tasks(user: User, project_public_id: UUID) -> list[dict[str, Any]] | None:
    from apps.work_items.models import Task

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    return [
        {
            "public_id": str(task.public_id),
            "task_code": task.task_code,
            "name": task.name,
            "stage_code": task.stage.stage_code,
            "status": task.status,
            "is_core": task.is_core,
            "version_no": task.version_no,
            "responsible_user_public_id": (
                str(task.responsible_user.public_id) if task.responsible_user_id else None
            ),
            "responsible_department_public_id": str(task.responsible_department.public_id),
        }
        for task in Task.objects.filter(project=project)
        .select_related("stage", "responsible_user", "responsible_department")
        .order_by("stage__sequence_no", "task_code")
    ]


def list_project_deliverables(
    user: User, project_public_id: UUID
) -> list[dict[str, Any]] | None:
    from apps.work_items.models import Deliverable

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    return [
        {
            "public_id": str(item.public_id),
            "deliverable_code": item.deliverable_code,
            "name": item.name,
            "stage_code": item.stage.stage_code,
            "tier": item.tier,
            "status": item.status,
            "current_revision_public_id": (
                str(item.current_revision.public_id) if item.current_revision_id else None
            ),
        }
        for item in Deliverable.objects.filter(project=project)
        .select_related("stage", "current_revision")
        .order_by("stage__sequence_no", "deliverable_code")
    ]
