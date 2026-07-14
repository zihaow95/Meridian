"""Product dossier read APIs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError
from apps.products.api.schemas import PRODUCT_DETAIL_SCHEMA, PRODUCT_SEARCH_PAGE_SCHEMA
from apps.products.queries.products import get_product_detail, search_products


def _positive_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class ProductListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="products_list",
        parameters=[
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="brand_code", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="category_code", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="lifecycle_status", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="owner_public_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="sku_code", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="external_id", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="channel_code", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY),
        ],
        responses=PRODUCT_SEARCH_PAGE_SCHEMA,
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        page = search_products(
            user=user,
            search=request.query_params.get("search", ""),
            brand_code=request.query_params.get("brand_code", ""),
            category_code=request.query_params.get("category_code", ""),
            lifecycle_status=request.query_params.get("lifecycle_status", ""),
            owner_public_id=request.query_params.get("owner_public_id", ""),
            sku_code=request.query_params.get("sku_code", ""),
            external_id=request.query_params.get("external_id", ""),
            channel_code=request.query_params.get("channel_code", ""),
            page=_positive_int(request.query_params.get("page"), 1),
            page_size=_positive_int(request.query_params.get("page_size"), 20),
        )
        return Response(
            {
                "items": page.items,
                "page": page.page,
                "page_size": page.page_size,
                "count": page.count,
            }
        )


class ProductDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="products_retrieve", responses=PRODUCT_DETAIL_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        detail = get_product_detail(user=user, public_id=public_id)
        if detail is None:
            raise ResourceNotFoundError()
        return Response(detail)
