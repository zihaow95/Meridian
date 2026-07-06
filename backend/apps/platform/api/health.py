"""Health endpoint.

Returns a fixed structure only. It intentionally exposes no version, database
address, filesystem path or secret, so it cannot leak runtime details.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        operation_id="health_retrieve",
        summary="Liveness/readiness probe",
        responses=inline_serializer(
            name="HealthResponse",
            fields={
                "status": serializers.CharField(),
                "service": serializers.CharField(),
            },
        ),
        examples=[
            OpenApiExample(
                "ok",
                value={"status": "ok", "service": "meridian-api"},
                response_only=True,
            )
        ],
    )
    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "service": "meridian-api"})
