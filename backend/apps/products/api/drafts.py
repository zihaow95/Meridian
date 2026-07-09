"""Read-only product draft detail API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError
from apps.products.models import ProductDraft
from apps.products.queries.drafts import serialize_product_draft_detail


class ProductDraftDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        draft = (
            ProductDraft.objects.select_related(
                "product_asset",
                "target_product_asset",
                "project_candidate",
            )
            .filter(public_id=public_id, organization_id=user.organization_id)
            .first()
        )
        if draft is None:
            raise ResourceNotFoundError()
        return Response(serialize_product_draft_detail(draft))
