"""Read-only product draft detail API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import PRODUCT_DRAFT_DETAIL_SCHEMA
from apps.platform.api.errors import ResourceNotFoundError
from apps.products.models import ProductChangeSet
from apps.products.queries.drafts import serialize_product_draft_detail
from apps.products.services.access import assert_can_read_change_set


class ProductDraftDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="product_drafts_retrieve", responses=PRODUCT_DRAFT_DETAIL_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change_set = (
            ProductChangeSet.objects.select_related(
                "product",
                "target_product_asset",
                "project_candidate",
            )
            .filter(public_id=public_id, organization_id=user.organization_id)
            .first()
        )
        if change_set is None:
            raise ResourceNotFoundError()
        assert_can_read_change_set(user=user, change_set=change_set)
        return Response(serialize_product_draft_detail(change_set))
