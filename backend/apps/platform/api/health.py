"""Health endpoint.

Returns a fixed structure only. It intentionally exposes no version, database
address, filesystem path or secret, so it cannot leak runtime details.
"""

from __future__ import annotations

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "service": "meridian-api"})
