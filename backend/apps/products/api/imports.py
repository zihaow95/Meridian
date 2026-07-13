"""Product legacy import APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError, ResourceNotFoundError
from apps.platform.application.command import CommandContext
from apps.products.api.schemas import (
    DECIDE_IMPORT_ITEM_REQUEST_SCHEMA,
    DECIDE_IMPORT_ITEM_RESPONSE_SCHEMA,
)
from apps.products.models import ImportBatch
from apps.products.services.import_batch import (
    ConfirmProductImportBatch,
    CreateProductImportBatch,
    DecideImportItem,
)
from apps.products.services.publish_legacy_baseline import PublishLegacyBaseline

IMPORT_BATCH_DETAIL_SCHEMA = inline_serializer(
    name="ImportBatchDetail",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "template_version": serializers.CharField(),
        "total_count": serializers.IntegerField(),
        "success_count": serializers.IntegerField(),
        "failure_count": serializers.IntegerField(),
        "items": serializers.ListField(),
    },
)

CONFIRM_IMPORT_REQUEST_SCHEMA = inline_serializer(
    name="ConfirmImportBatchRequest",
    fields={
        "idempotency_key": serializers.CharField(),
    },
)

CONFIRM_IMPORT_RESPONSE_SCHEMA = inline_serializer(
    name="ConfirmImportBatchResponse",
    fields={
        "created_count": serializers.IntegerField(),
        "linked_count": serializers.IntegerField(),
        "skipped_count": serializers.IntegerField(),
        "failed_count": serializers.IntegerField(),
        "items": serializers.ListField(),
    },
)

PUBLISH_BASELINE_RESPONSE_SCHEMA = inline_serializer(
    name="PublishLegacyBaselineResponse",
    fields={
        "change_set_public_id": serializers.UUIDField(),
        "product_version_public_id": serializers.UUIDField(),
        "product_lifecycle_status": serializers.CharField(),
    },
)


def serialize_import_batch(batch: ImportBatch) -> dict[str, Any]:
    items = [
        {
            "row_number": item.row_number,
            "item_status": item.item_status,
            "validation_errors": item.validation_errors,
            "duplicate_candidates": item.duplicate_candidates,
            "baseline_public_id": (
                str(baseline.public_id)
                if (baseline := item.baseline_change_set) is not None
                else None
            ),
        }
        for item in batch.items.order_by("row_number")
    ]
    return {
        "public_id": str(batch.public_id),
        "status": batch.status,
        "template_version": batch.template_version,
        "total_count": batch.total_count,
        "success_count": batch.success_count,
        "failure_count": batch.failure_count,
        "items": items,
    }


class ProductImportBatchCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_import_batches_create",
        request=inline_serializer(
            name="CreateImportBatchRequest",
            fields={
                "csv_content": serializers.CharField(),
                "source_filename": serializers.CharField(required=False),
            },
        ),
        responses=IMPORT_BATCH_DETAIL_SCHEMA,
    )
    def post(self, request: Request) -> Response:
        user = request.user
        assert isinstance(user, User)
        body = request.data
        batch = CreateProductImportBatch(
            context=CommandContext.for_actor(user),
            csv_content=str(body["csv_content"]),
            source_filename=str(body.get("source_filename") or "import.csv"),
        ).execute()
        batch = ImportBatch.objects.prefetch_related("items").get(pk=batch.pk)
        return Response(serialize_import_batch(batch), status=201)


class ProductImportBatchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_import_batches_retrieve",
        responses=IMPORT_BATCH_DETAIL_SCHEMA,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = request.user
        assert isinstance(user, User)
        decision = authorize(
            subject_for(user),
            action="migration.review",
            resource=ResourceDescriptor(
                resource_type="migration",
                public_id=None,
                organization_id=user.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()
        batch = (
            ImportBatch.objects.prefetch_related("items")
            .filter(public_id=public_id, organization_id=user.organization_id)
            .first()
        )
        if batch is None:
            raise ResourceNotFoundError()
        return Response(serialize_import_batch(batch))


class ProductImportBatchConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_import_batches_confirm",
        request=CONFIRM_IMPORT_REQUEST_SCHEMA,
        responses=CONFIRM_IMPORT_RESPONSE_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = request.user
        assert isinstance(user, User)
        body = request.data
        result = ConfirmProductImportBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
            idempotency_key=str(body.get("idempotency_key") or "confirm-import"),
        ).execute()
        return Response(
            {
                "created_count": result.created_count,
                "linked_count": result.linked_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
                "items": [
                    {
                        "row_number": item.row_number,
                        "baseline_public_id": item.baseline_public_id,
                        "item_status": item.item_status,
                    }
                    for item in result.items
                ],
            }
        )


class ProductImportItemDecideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_import_items_decide",
        request=DECIDE_IMPORT_ITEM_REQUEST_SCHEMA,
        responses=DECIDE_IMPORT_ITEM_RESPONSE_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = request.user
        assert isinstance(user, User)
        body = request.data
        target_id = body.get("target_product_public_id")
        item = DecideImportItem(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
            row_number=int(body["row_number"]),
            decision=str(body["decision"]),
            target_product_public_id=UUID(str(target_id)) if target_id else None,
        ).execute()
        return Response(
            {
                "row_number": item.row_number,
                "decision": item.decision,
                "target_product_public_id": (
                    str(target.public_id) if (target := item.target_product) is not None else None
                ),
            }
        )


class PublishLegacyBaselineView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="legacy_baselines_publish",
        request=CONFIRM_IMPORT_REQUEST_SCHEMA,
        responses=PUBLISH_BASELINE_RESPONSE_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = request.user
        assert isinstance(user, User)
        body = request.data or {}
        result = PublishLegacyBaseline(
            context=CommandContext.for_actor(user),
            baseline_public_id=public_id,
            idempotency_key=str(body.get("idempotency_key") or "legacy-baseline-publish"),
        ).execute()
        return Response(
            {
                "change_set_public_id": str(result.change_set.public_id),
                "product_version_public_id": str(result.product_version.public_id),
                "product_lifecycle_status": result.change_set.product.lifecycle_status,
            }
        )
