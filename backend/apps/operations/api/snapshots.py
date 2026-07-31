"""Operating data snapshot APIs (retirement evidence)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.services.data_snapshots import CreateRetirementEvidenceSnapshot
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

SNAPSHOT_SCHEMA = inline_serializer(
    name="OperatingDataSnapshot",
    fields={
        "public_id": serializers.UUIDField(),
        "purpose": serializers.CharField(),
        "content_hash": serializers.CharField(),
    },
)


class OperatingDataSnapshotCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_snapshots_create",
        request=inline_serializer(
            name="OperatingDataSnapshotCreateRequest",
            fields={
                "product_public_id": serializers.UUIDField(),
                "evidence": serializers.DictField(),
                "metric_codes": serializers.ListField(
                    child=serializers.CharField(), required=False
                ),
                "periods": serializers.ListField(required=False),
            },
        ),
        responses={201: SNAPSHOT_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        product_public_id = data.get("product_public_id")
        evidence = data.get("evidence")
        if not product_public_id or not isinstance(evidence, dict) or not evidence:
            raise ValidationFailedError(message="product_public_id and evidence are required.")
        snapshot = CreateRetirementEvidenceSnapshot(
            context=CommandContext.for_actor(user),
            product_public_id=UUID(str(product_public_id)),
            evidence=dict(evidence),
            metric_codes=list(data.get("metric_codes") or ["GROSS_SALES"]),
            periods=list(data.get("periods") or []),
        ).execute()
        return Response(
            {
                "public_id": str(snapshot.public_id),
                "purpose": snapshot.purpose,
                "content_hash": snapshot.content_hash,
            },
            status=201,
        )
