"""Shared query-param parsing for operations list endpoints."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter
from rest_framework.request import Request

from apps.operations.queries.pagination import DEFAULT_PAGE_SIZE
from apps.platform.api.errors import ValidationFailedError

PAGE_QUERY_PARAMETERS = [
    OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY),
]


def _parse_page_param(raw: object | None, *, default: int) -> int:
    if raw in (None, ""):
        return default
    try:
        parsed = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError(message="Invalid pagination parameter.") from exc
    if parsed < 1:
        raise ValidationFailedError(message="Invalid pagination parameter.")
    return parsed


def page_params(request: Request) -> tuple[int, int]:
    page = _parse_page_param(request.query_params.get("page"), default=1)
    page_size = _parse_page_param(request.query_params.get("page_size"), default=DEFAULT_PAGE_SIZE)
    return page, page_size
