"""Internal test-only endpoints for contract verification."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform.api.errors import ResourceNotFoundError


class HiddenResourceView(APIView):
    """Always responds with a 404-style hidden resource error."""

    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request: Request) -> Response:
        raise ResourceNotFoundError()
