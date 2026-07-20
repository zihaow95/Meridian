"""Permission-filtered project workbench queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
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
        .filter(Q(leader=user) | Q(deputy_leader=user) | Q(id__in=membership_ids))
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
                project.current_stage.stage_code if project.current_stage is not None else None
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


def _launch_capabilities(user: User, project: Project) -> dict[str, bool]:
    """Resolve which FIRST_LAUNCH decision actions the actor may perform.

    The panel hides actions the actor cannot take; the backend still enforces
    them, so a hidden action that is somehow invoked returns 403.
    """

    from apps.stage_gates.models import GateType, StageGateInstance

    gate = (
        StageGateInstance.objects.select_related("project_stage")
        .filter(project=project, gate_type=GateType.MAJOR)
        .filter(Q(stage_code="FIRST_LAUNCH") | Q(project_stage__gate_code="FIRST_LAUNCH"))
        .order_by("-created_at")
        .first()
    )
    can_management = False
    can_final = False
    if gate is not None:
        subject = subject_for(user)
        resource = ResourceDescriptor(
            resource_type="stage_gate",
            public_id=gate.public_id,
            organization_id=gate.organization_id,
        )
        auth_context = AuthorizationContext.current()
        can_management = authorize(
            subject,
            action="first_launch.management_conclusion.record",
            resource=resource,
            context=auth_context,
        ).allowed
        can_final = authorize(
            subject,
            action="first_launch.final_decision.record",
            resource=resource,
            context=auth_context,
        ).allowed
    return {
        "can_record_management_conclusion": can_management,
        "can_record_final_decision": can_final,
    }


def _can_publish_repair(user: User, project: Project) -> bool:
    """Whether the actor may re-run publish handover for this project."""

    return authorize(
        subject_for(user),
        action="project.publish_repair",
        resource=ResourceDescriptor(
            resource_type="project",
            public_id=project.public_id,
            organization_id=project.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


def _can_download_documents(user: User) -> bool:
    """Whether the actor may request document download tickets."""

    return authorize(
        subject_for(user),
        action="document.version.download",
        resource=ResourceDescriptor(
            resource_type="document.version",
            public_id=None,
            organization_id=user.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


def serialize_workbench_project(project: Project, *, user: User) -> dict[str, Any]:
    payload = serialize_project_detail(project)
    payload["current_stage_code"] = (
        project.current_stage.stage_code if project.current_stage is not None else None
    )
    payload["launch_capabilities"] = _launch_capabilities(user, project)
    payload["can_publish_repair"] = _can_publish_repair(user, project)
    payload["can_download_documents"] = _can_download_documents(user)
    return payload


def list_project_stages(
    user: User,
    project_public_id: UUID,
    *,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> ProjectSearchPage | None:
    from apps.stage_gates.models import StageGateInstance

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)
    gates_by_stage = {
        gate.project_stage_id: gate
        for gate in StageGateInstance.objects.filter(
            project=project, project_stage_id__isnull=False
        )
    }
    qs = ProjectStage.objects.filter(project=project).order_by("sequence_no")
    count = qs.count()
    offset = (page - 1) * page_size
    items = [
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
        for stage in qs[offset : offset + page_size]
    ]
    return ProjectSearchPage(items=items, page=page, page_size=page_size, count=count)


def list_project_tasks(
    user: User,
    project_public_id: UUID,
    *,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> ProjectSearchPage | None:
    from apps.work_items.models import Task

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)
    qs = (
        Task.objects.filter(project=project)
        .select_related("stage", "responsible_user", "responsible_department")
        .order_by("stage__sequence_no", "task_code")
    )
    count = qs.count()
    offset = (page - 1) * page_size
    items = [
        {
            "public_id": str(task.public_id),
            "task_code": task.task_code,
            "name": task.name,
            "stage_code": task.stage.stage_code,
            "status": task.status,
            "is_core": task.is_core,
            "version_no": task.version_no,
            "responsible_user_public_id": (
                str(task.responsible_user.public_id) if task.responsible_user is not None else None
            ),
            "responsible_department_public_id": str(task.responsible_department.public_id),
        }
        for task in qs[offset : offset + page_size]
    ]
    return ProjectSearchPage(items=items, page=page, page_size=page_size, count=count)


def list_project_deliverables(
    user: User,
    project_public_id: UUID,
    *,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> ProjectSearchPage | None:
    from apps.work_items.models import Deliverable

    project = get_project_for_user(user, project_public_id)
    if project is None:
        return None
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)
    qs = (
        Deliverable.objects.filter(project=project)
        .select_related("stage", "current_revision", "current_revision__document_version")
        .order_by("stage__sequence_no", "deliverable_code")
    )
    count = qs.count()
    offset = (page - 1) * page_size
    items = [
        {
            "public_id": str(item.public_id),
            "deliverable_code": item.deliverable_code,
            "name": item.name,
            "stage_code": item.stage.stage_code,
            "tier": item.tier,
            "status": item.status,
            "current_revision_public_id": (
                str(item.current_revision.public_id) if item.current_revision is not None else None
            ),
            "document_version_public_id": (
                str(item.current_revision.document_version.public_id)
                if item.current_revision is not None
                and item.current_revision.document_version_id is not None
                else None
            ),
        }
        for item in qs[offset : offset + page_size]
    ]
    return ProjectSearchPage(items=items, page=page, page_size=page_size, count=count)
