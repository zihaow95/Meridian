"""Todo list API."""

from __future__ import annotations

from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.notifications.models import TodoStatus
from apps.notifications.queries.todos import list_my_todos
from apps.platform.api.errors import ValidationFailedError
from apps.platform.api.permissions import requires_action

TodoReadPermission = requires_action(
    action_code="notification.todo.read",
    resource_type="notification.todo",
)


class MyTodosView(APIView):
    permission_classes = [IsAuthenticated, TodoReadPermission]

    @extend_schema(
        operation_id="notification_todos_list",
        responses=inline_serializer(
            name="MyTodoListItem",
            fields={
                "public_id": serializers.CharField(),
                "title": serializers.CharField(),
                "status": serializers.CharField(),
                "due_at": serializers.CharField(allow_null=True),
                "deep_link": serializers.CharField(),
            },
            many=True,
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        status = request.query_params.get("status")
        if status and status not in TodoStatus.values:
            raise ValidationFailedError(details={"status": ["Invalid status filter."]})

        todos = list_my_todos(user=user, status=status or None)
        return Response(
            [
                {
                    "public_id": str(todo.public_id),
                    "title": todo.title,
                    "status": todo.status,
                    "due_at": todo.due_at.isoformat() if todo.due_at else None,
                    "deep_link": todo.deep_link,
                }
                for todo in todos
            ]
        )
