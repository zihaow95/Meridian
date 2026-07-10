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


class ProductListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="products_list",
        parameters=[
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY),
        ],
        responses=PRODUCT_SEARCH_PAGE_SCHEMA,
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        search = request.query_params.get("search", "")
        items = search_products(user=user, search=search)
        return Response({"items": items})


class ProductDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="products_retrieve", responses=PRODUCT_DETAIL_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        detail = get_product_detail(user=user, public_id=public_id)
        if detail is None:
            raise ResourceNotFoundError()
        return Response(detail)
