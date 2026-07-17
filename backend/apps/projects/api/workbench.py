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
from apps.projects.api.schemas import (
    CUSTOM_DELIVERABLE_CREATE_REQUEST,
    CUSTOM_TASK_CREATE_REQUEST,
    DELIVERABLES_RESPONSE,
    EMERGENCY_COMPLETE_REQUEST,
    EMERGENCY_CREATE_REQUEST,
    EMPTY_BODY_REQUEST,
    MEMBER_APPOINT_REQUEST,
    PLAN_CHANGE_REQUEST,
    PROJECT_DETAIL_RESPONSE,
    PROJECT_LIST_RESPONSE,
    PUBLIC_ID_STATUS,
    STAGE_HANDLING_REQUEST,
    STAGES_RESPONSE,
    TASKS_RESPONSE,
)
from apps.projects.queries.workbench import (
    get_project_for_user,
    list_project_deliverables,
    list_project_stages,
    list_project_tasks,
    search_projects,
    serialize_workbench_project,
)
from apps.projects.services.appoint_member import AppointProjectMember
from apps.projects.services.emergency_execution import (
    CompleteEmergencyExecution,
    CreateEmergencyExecution,
)
from apps.projects.services.exceptions import (
    ConfirmExecutionException,
    RequestStageHandlingMode,
)
from apps.projects.services.plan_changes import ApplyPlanChange, ConfirmPlanChange
from apps.projects.services.publish_and_handover import RetryPublishAndHandover
from apps.work_items.services.materialize_template import CreateCustomDeliverable, CreateCustomTask


def _page_params(request: Request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page") or 1)
        page_size = int(request.query_params.get("page_size") or 20)
    except ValueError as exc:
        raise ValidationFailedError(message="Invalid page or page_size.") from exc
    return page, page_size


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_list", responses={200: PROJECT_LIST_RESPONSE})
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        try:
            page = int(request.query_params.get("page") or 1)
            page_size = int(request.query_params.get("page_size") or 20)
        except ValueError as exc:
            raise ValidationFailedError(message="Invalid page or page_size.") from exc
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


class ProjectWorkbenchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_retrieve",
        responses={200: PROJECT_DETAIL_RESPONSE, 404: None},
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        project = get_project_for_user(user, public_id)
        if project is None:
            raise ResourceNotFoundError()
        return Response(serialize_workbench_project(project, user=user))


class ProjectStagesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_stages_list", responses={200: STAGES_RESPONSE})
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        page, page_size = _page_params(request)
        result = list_project_stages(user, public_id, page=page, page_size=page_size)
        if result is None:
            raise ResourceNotFoundError()
        return Response(
            {
                "items": result.items,
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )


class ProjectMembersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_members_create",
        request=MEMBER_APPOINT_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        user_public_id = request.data.get("user_public_id")
        if not user_public_id:
            raise ValidationFailedError(message="user_public_id is required.")
        member = AppointProjectMember(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            user_public_id=UUID(str(user_public_id)),
            project_role=str(request.data.get("project_role") or "MEMBER"),
        ).execute()
        return Response(
            {
                "public_id": str(member.public_id),
                "status": member.project_role,
            },
            status=201,
        )


class ProjectTasksCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_tasks_list", responses={200: TASKS_RESPONSE})
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        page, page_size = _page_params(request)
        result = list_project_tasks(user, public_id, page=page, page_size=page_size)
        if result is None:
            raise ResourceNotFoundError()
        return Response(
            {
                "items": result.items,
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )

    @extend_schema(
        operation_id="projects_tasks_create",
        request=CUSTOM_TASK_CREATE_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        stage_public_id = request.data.get("stage_public_id")
        task_code = str(request.data.get("task_code") or "").strip()
        name = str(request.data.get("name") or "").strip()
        dept = request.data.get("responsible_department_public_id")
        if not stage_public_id or not task_code or not name or not dept:
            raise ValidationFailedError(
                message=(
                    "stage_public_id, task_code, name, and "
                    "responsible_department_public_id are required."
                )
            )
        task = CreateCustomTask(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            stage_public_id=UUID(str(stage_public_id)),
            task_code=task_code,
            name=name,
            responsible_department_public_id=UUID(str(dept)),
            is_core=bool(request.data.get("is_core", False)),
            description=str(request.data.get("description") or ""),
        ).execute()
        return Response(
            {
                "public_id": str(task.public_id),
                "status": task.status,
                "version_no": task.version_no,
            },
            status=201,
        )


class ProjectDeliverablesCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_deliverables_list", responses={200: DELIVERABLES_RESPONSE}
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        page, page_size = _page_params(request)
        result = list_project_deliverables(user, public_id, page=page, page_size=page_size)
        if result is None:
            raise ResourceNotFoundError()
        return Response(
            {
                "items": result.items,
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )

    @extend_schema(
        operation_id="projects_deliverables_create",
        request=CUSTOM_DELIVERABLE_CREATE_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        stage_public_id = request.data.get("stage_public_id")
        deliverable_code = str(request.data.get("deliverable_code") or "").strip()
        name = str(request.data.get("name") or "").strip()
        if not stage_public_id or not deliverable_code or not name:
            raise ValidationFailedError(
                message="stage_public_id, deliverable_code, and name are required."
            )
        item = CreateCustomDeliverable(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            stage_public_id=UUID(str(stage_public_id)),
            deliverable_code=deliverable_code,
            name=name,
            requires_professional_confirmation=bool(
                request.data.get("requires_professional_confirmation", True)
            ),
        ).execute()
        return Response({"public_id": str(item.public_id), "status": item.status}, status=201)


class ProjectPlanChangesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_plan_changes_create",
        request=PLAN_CHANGE_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        target_public_id = request.data.get("target_public_id")
        change_type = str(request.data.get("change_type") or "")
        field_name = str(request.data.get("field_name") or "")
        after_value = str(request.data.get("after_value") or "")
        before_value = str(request.data.get("before_value") or "")
        impact_summary = str(request.data.get("impact_summary") or "")
        target_type = str(request.data.get("target_type") or "project_stage")
        if not target_public_id:
            raise ValidationFailedError(message="target_public_id is required.")
        change = ApplyPlanChange(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
            change_type=change_type,
            target_type=target_type,
            target_public_id=UUID(str(target_public_id)),
            field_name=field_name,
            before_value=before_value,
            after_value=after_value,
            impact_summary=impact_summary,
        ).execute()
        return Response(
            {
                "public_id": str(change.public_id),
                "status": change.status,
            },
            status=201,
        )


class PlanChangeConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="plan_changes_confirm",
        request=EMPTY_BODY_REQUEST,
        responses={200: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change = ConfirmPlanChange(
            context=CommandContext.for_actor(user),
            change_public_id=public_id,
        ).execute()
        return Response({"public_id": str(change.public_id), "status": change.status})


class ProjectStageHandlingRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_stages_handling_request",
        request=STAGE_HANDLING_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        exception = RequestStageHandlingMode(
            context=CommandContext.for_actor(user),
            stage_public_id=public_id,
            requested_mode=str(request.data.get("requested_mode") or ""),
            rationale=str(request.data.get("rationale") or ""),
        ).execute()
        return Response(
            {"public_id": str(exception.public_id), "status": exception.status},
            status=201,
        )


class ExecutionExceptionConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="execution_exceptions_confirm",
        request=EMPTY_BODY_REQUEST,
        responses={200: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        exception = ConfirmExecutionException(
            context=CommandContext.for_actor(user),
            exception_public_id=public_id,
        ).execute()
        return Response({"public_id": str(exception.public_id), "status": exception.status})


class ProjectEmergencyExecutionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_emergency_executions_create",
        request=EMERGENCY_CREATE_REQUEST,
        responses={201: PUBLIC_ID_STATUS},
    )
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
            },
            status=201,
        )


class EmergencyExecutionCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="emergency_executions_complete",
        request=EMERGENCY_COMPLETE_REQUEST,
        responses={200: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        item = CompleteEmergencyExecution(
            context=CommandContext.for_actor(user),
            emergency_public_id=public_id,
            confirmation_summary=str(request.data.get("confirmation_summary") or ""),
        ).execute()
        return Response({"public_id": str(item.public_id), "status": item.status})


class ProjectPublishRepairView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_publish_repair_create",
        request=EMPTY_BODY_REQUEST,
        responses={200: PUBLIC_ID_STATUS},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        result = RetryPublishAndHandover(
            context=CommandContext.for_actor(user),
            project_public_id=public_id,
        ).execute()
        return Response(
            {
                "public_id": str(result.project.public_id),
                "status": result.project.status,
                "handover_error": result.error_code,
            }
        )
