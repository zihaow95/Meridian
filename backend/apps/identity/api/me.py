"""Current authenticated user profile."""

from __future__ import annotations

from typing import cast

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="me_retrieve",
        summary="Current authenticated user",
        responses=inline_serializer(
            name="MeResponse",
            fields={
                "public_id": serializers.UUIDField(),
                "display_name": serializers.CharField(),
                "status": serializers.CharField(),
            },
        ),
    )
    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        return Response(
            {
                "public_id": str(user.public_id),
                "display_name": user.display_name,
                "status": user.status,
            }
        )
