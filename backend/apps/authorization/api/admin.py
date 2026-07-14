"""Minimal authorization administration API."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.models.role import Role
from apps.platform.api.permissions import requires_action

RoleReadPermission = requires_action(
    action_code="authorization.role.read",
    resource_type="authorization.role",
)


class RoleCatalogView(APIView):
    permission_classes = [IsAuthenticated, RoleReadPermission]

    @extend_schema(
        operation_id="authorization_roles_list",
        responses=inline_serializer(
            name="RoleCatalogItem",
            fields={
                "public_id": serializers.CharField(),
                "role_code": serializers.CharField(),
                "name": serializers.CharField(),
                "role_type": serializers.CharField(),
                "is_critical": serializers.BooleanField(),
            },
            many=True,
        ),
    )
    def get(self, request: Request) -> Response:
        roles = Role.objects.filter(status="ACTIVE").order_by("role_code")
        return Response(
            [
                {
                    "public_id": str(role.public_id),
                    "role_code": role.role_code,
                    "name": role.name,
                    "role_type": role.role_type,
                    "is_critical": role.is_critical,
                }
                for role in roles
            ]
        )
