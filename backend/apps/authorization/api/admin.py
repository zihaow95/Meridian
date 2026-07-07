"""Minimal authorization administration API."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.models.role import Role


class RoleCatalogView(APIView):
    permission_classes = [IsAuthenticated]

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
