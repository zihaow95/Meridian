"""Task and assignment APIs for project execution."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.work_items.services.manage_tasks import AssignTaskResponsible, TransitionTask

EMPTY_BODY_REQUEST = inline_serializer(
    name="TaskEmptyBodyRequest",
    fields={},
)

TASK_ASSIGN_REQUEST = inline_serializer(
    name="TaskAssignRequest",
    fields={
        "user_public_id": serializers.UUIDField(),
        "version_no": serializers.IntegerField(),
    },
)

TASK_TRANSITION_REQUEST = inline_serializer(
    name="TaskTransitionRequest",
    fields={
        "status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
    },
)

TASK_RESPONSE = inline_serializer(
    name="TaskCommandResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(required=False),
        "version_no": serializers.IntegerField(required=False),
        "responsible_user_public_id": serializers.UUIDField(required=False, allow_null=True),
    },
)


class TaskUpdateView(APIView):
    """Deprecated status mutation alias — prefer POST .../transition."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tasks_partial_update",
        request=EMPTY_BODY_REQUEST,
        responses={405: None},
    )
    def patch(self, request: Request, public_id: UUID) -> Response:
        del request, public_id
        return Response(
            {
                "code": "METHOD_NOT_ALLOWED",
                "message": "Use POST /api/v1/tasks/{id}/transition to change task status.",
                "details": {},
                "trace_id": "",
            },
            status=405,
        )


class TaskTransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tasks_transition",
        request=TASK_TRANSITION_REQUEST,
        responses={200: TASK_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        target_status = request.data.get("status")
        version_no = request.data.get("version_no")
        if target_status is None or version_no is None:
            raise ValidationFailedError(message="status and version_no are required.")
        task = TransitionTask(
            context=CommandContext.for_actor(user),
            task_public_id=public_id,
            target_status=str(target_status),
            version_no=int(version_no),
        ).execute()
        return Response(
            {
                "public_id": str(task.public_id),
                "status": task.status,
                "version_no": task.version_no,
            }
        )


class TaskAssignView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="tasks_assign",
        request=TASK_ASSIGN_REQUEST,
        responses={200: TASK_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        user_public_id = request.data.get("user_public_id")
        version_no = request.data.get("version_no")
        if user_public_id is None or version_no is None:
            raise ValidationFailedError(message="user_public_id and version_no are required.")
        task = AssignTaskResponsible(
            context=CommandContext.for_actor(user),
            task_public_id=public_id,
            user_public_id=UUID(str(user_public_id)),
            version_no=int(version_no),
        ).execute()
        return Response(
            {
                "public_id": str(task.public_id),
                "responsible_user_public_id": (
                    str(task.responsible_user.public_id)
                    if task.responsible_user is not None
                    else None
                ),
                "version_no": task.version_no,
            }
        )
