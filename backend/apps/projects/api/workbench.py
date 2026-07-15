"""Project workbench list/detail/stages and execution command APIs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.projects.api.projects import ProjectDetailView
from apps.projects.queries.workbench import (
    get_project_for_user,
    list_project_deliverables,
    list_project_stages,
    list_project_tasks,
    search_projects,
    serialize_workbench_project,
)
from apps.projects.services.emergency_execution import CreateEmergencyExecution
from apps.projects.services.plan_changes import ApplyPlanChange


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_list")
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        page = int(request.query_params.get("page") or 1)
        page_size = int(request.query_params.get("page_size") or 20)
        status = request.query_params.get("status") or None
        result = search_projects(user, page=page, page_size=page_size, status=status)
        return Response(
            {
                "items": result.items,
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )


class ProjectWorkbenchDetailView(ProjectDetailView):
    """Override detail to enforce membership visibility."""

    @extend_schema(operation_id="projects_retrieve")
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        project = get_project_for_user(user, public_id)
        if project is None:
            raise ResourceNotFoundError()
        return Response(serialize_workbench_project(project))


class ProjectStagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_stages_list")
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        items = list_project_stages(user, public_id)
        if items is None:
            raise ResourceNotFoundError()
        return Response({"items": items})


class ProjectTasksCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_tasks_list")
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        items = list_project_tasks(user, public_id)
        if items is None:
            raise ResourceNotFoundError()
        return Response({"items": items})


class ProjectDeliverablesCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_deliverables_list")
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        items = list_project_deliverables(user, public_id)
        if items is None:
            raise ResourceNotFoundError()
        return Response({"items": items})


class ProjectPlanChangesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_plan_changes_create")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        stage_public_id = request.data.get("target_public_id") or request.data.get(
            "stage_public_id"
        )
        change_type = str(request.data.get("change_type") or "")
        field_name = str(request.data.get("field_name") or "")
        after_value = str(request.data.get("after_value") or "")
        before_value = str(request.data.get("before_value") or "")
        impact_summary = str(request.data.get("impact_summary") or "")
        target_type = str(request.data.get("target_type") or "project_stage")
        if not stage_public_id:
            raise ValidationFailedError(message="target_public_id is required.")
        change = ApplyPlanChange(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            change_type=change_type,
            target_type=target_type,
            target_public_id=UUID(str(stage_public_id)),
            field_name=field_name,
            before_value=before_value,
            after_value=after_value,
            impact_summary=impact_summary,
        ).execute()
        return Response(
            {
                "public_id": str(change.public_id),
                "change_type": change.change_type,
                "status": change.status,
            },
            status=201,
        )


class ProjectEmergencyExecutionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_emergency_executions_create")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        due_raw = request.data.get("due_at")
        due_at = parse_datetime(str(due_raw or ""))
        if due_at is None:
            raise ValidationFailedError(message="due_at is required.")
        item = CreateEmergencyExecution(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            subject_summary=str(request.data.get("subject_summary") or ""),
            pending_confirmation=str(request.data.get("pending_confirmation") or ""),
            due_at=due_at,
        ).execute()
        return Response(
            {
                "public_id": str(item.public_id),
                "status": item.status,
                "due_at": item.due_at.isoformat(),
            },
            status=201,
        )
