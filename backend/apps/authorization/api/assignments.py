"""Role assignment administration API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.models.assignment import RoleAssignment
from apps.authorization.models.role import Role
from apps.authorization.services.assign_role import AssignRole, RoleAssignmentDenied
from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action

RoleAssignPermission = requires_action(
    action_code="authorization.role.assign",
    resource_type="authorization.role",
)


class UserAssignmentsView(APIView):
    permission_classes = [IsAuthenticated, RoleAssignPermission]

    @extend_schema(
        operation_id="authorization_user_assignments_list",
        responses=inline_serializer(
            name="UserAssignmentListItem",
            fields={
                "public_id": serializers.CharField(),
                "role_code": serializers.CharField(),
                "role_name": serializers.CharField(),
                "scope_type": serializers.CharField(),
                "status": serializers.CharField(),
            },
            many=True,
        ),
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        actor = cast(User, request.user)
        target = User.objects.filter(
            public_id=public_id,
            organization_id=actor.organization_id,
        ).first()
        if target is None:
            raise ResourceNotFoundError()

        assignments = RoleAssignment.objects.filter(user=target).select_related("role")
        return Response(
            [
                {
                    "public_id": str(assignment.public_id),
                    "role_code": assignment.role.role_code,
                    "role_name": assignment.role.name,
                    "scope_type": assignment.scope_type,
                    "status": assignment.status,
                }
                for assignment in assignments
            ]
        )

    @extend_schema(
        operation_id="authorization_user_assignments_create",
        request=inline_serializer(
            name="UserAssignmentCreateRequest",
            fields={
                "role_code": serializers.CharField(),
                "approval_reference": serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={
            201: inline_serializer(
                name="UserAssignmentCreateResponse",
                fields={
                    "public_id": serializers.CharField(),
                    "role_code": serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        actor = cast(User, request.user)
        target = User.objects.filter(
            public_id=public_id,
            organization_id=actor.organization_id,
        ).first()
        if target is None:
            raise ResourceNotFoundError()

        role_code = request.data.get("role_code")
        if not role_code:
            raise ValidationFailedError(details={"role_code": ["This field is required."]})

        role = Role.objects.filter(role_code=role_code, status="ACTIVE").first()
        if role is None:
            raise ResourceNotFoundError()

        approval_reference = request.data.get("approval_reference", "")
        try:
            assignment = AssignRole(
                actor=actor,
                target=target,
                role=role,
                approval_reference=approval_reference,
            ).execute()
        except RoleAssignmentDenied as exc:
            raise ResourceNotFoundError() from exc
        except ValueError as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        return Response(
            {
                "public_id": str(assignment.public_id),
                "role_code": role.role_code,
            },
            status=201,
        )
