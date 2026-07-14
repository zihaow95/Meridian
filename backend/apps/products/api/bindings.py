"""External binding management APIs for product dossiers."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.integrations.services.external_binding import ExternalBindingInput, UpsertExternalBinding
from apps.platform.api.errors import ResourceNotFoundError
from apps.platform.application.command import CommandContext
from apps.products.api.schemas import (
    EXTERNAL_BINDING_SCHEMA,
    UPSERT_EXTERNAL_BINDING_REQUEST_SCHEMA,
)
from apps.products.models import ProductAsset


class ProductExternalBindingUpsertView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="products_external_bindings_upsert",
        request=UPSERT_EXTERNAL_BINDING_REQUEST_SCHEMA,
        responses=EXTERNAL_BINDING_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = ProductAsset.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        ).first()
        if product is None:
            raise ResourceNotFoundError()

        body = request.data
        binding = UpsertExternalBinding(
            context=CommandContext.for_actor(user),
            product_public_id=public_id,
            binding=ExternalBindingInput(
                source_system=str(body["source_system"]),
                object_type=str(body["object_type"]),
                external_id=str(body["external_id"]),
                internal_object_type="product",
                internal_object_id=product.id,
            ),
        ).execute()
        return Response(
            {
                "public_id": str(binding.public_id),
                "source_system": binding.source_system,
                "object_type": binding.object_type,
                "external_id": binding.external_id,
                "binding_status": binding.binding_status,
            },
            status=200,
        )
