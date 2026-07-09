"""Lifecycle board read API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import LIFECYCLE_BOARD_PAGE_SCHEMA
from apps.opportunities.queries.lifecycle_board import query_lifecycle_board
from apps.platform.api.errors import ValidationFailedError


def _optional_uuid(value: object | None, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(message=f"Invalid {field}.") from exc


def _positive_int(value: object | None, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError(message="Invalid pagination parameter.") from exc
    if parsed < 1:
        raise ValidationFailedError(message="Invalid pagination parameter.")
    return parsed


class LifecycleBoardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="lifecycle_board_list", responses=LIFECYCLE_BOARD_PAGE_SCHEMA)
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        page = query_lifecycle_board(
            user,
            lifecycle_stage=(
                str(request.query_params.get("lifecycle_stage"))
                if request.query_params.get("lifecycle_stage")
                else None
            ),
            status=(
                str(request.query_params.get("status"))
                if request.query_params.get("status")
                else None
            ),
            owner_public_id=_optional_uuid(request.query_params.get("owner"), "owner"),
            page=_positive_int(request.query_params.get("page"), 1),
            page_size=_positive_int(request.query_params.get("page_size"), 20),
        )
        return Response(
            {
                "items": page.items,
                "page": page.page,
                "page_size": page.page_size,
                "total_count": page.total_count,
                "has_more": page.has_more,
            }
        )
