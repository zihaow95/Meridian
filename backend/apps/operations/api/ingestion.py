"""Operating ingestion batch APIs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.integrations.models import IngestionBatch, IngestionRow
from apps.integrations.services.ingestion import CreateIngestionBatch, RetryIngestionBatch
from apps.operations.queries.visible_resources import list_unmapped_ingestion_rows
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext

BATCH_SCHEMA = inline_serializer(
    name="OperatingIngestionBatch",
    fields={
        "public_id": serializers.UUIDField(),
        "batch_key": serializers.CharField(),
        "source_public_id": serializers.UUIDField(),
        "source_type": serializers.CharField(),
        "status": serializers.CharField(),
        "total_count": serializers.IntegerField(),
        "success_count": serializers.IntegerField(),
        "warning_count": serializers.IntegerField(),
        "error_count": serializers.IntegerField(),
        "skipped_count": serializers.IntegerField(),
        "added_count": serializers.IntegerField(),
        "revision_count": serializers.IntegerField(),
        "rows": serializers.ListField(required=False),
    },
)

BATCH_CREATE_REQUEST = inline_serializer(
    name="OperatingIngestionBatchCreateRequest",
    fields={
        "source_public_id": serializers.UUIDField(),
        "batch_key": serializers.CharField(),
        "source_type": serializers.CharField(),
        "rows": serializers.ListField(required=False),
        "input_file_version_public_id": serializers.UUIDField(required=False, allow_null=True),
    },
)

CONFIRM_REQUEST = inline_serializer(
    name="OperatingIngestionBatchConfirmRequest",
    fields={
        "idempotency_key": serializers.CharField(),
        "confirm_warnings": serializers.BooleanField(required=False),
    },
)

CONFIRM_RESPONSE = inline_serializer(
    name="OperatingIngestionBatchConfirmResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "added_count": serializers.IntegerField(),
        "revision_count": serializers.IntegerField(),
        "skipped_count": serializers.IntegerField(),
        "error_count": serializers.IntegerField(),
        "warning_count": serializers.IntegerField(),
    },
)


def serialize_row(row: IngestionRow) -> dict[str, Any]:
    return {
        "public_id": str(row.public_id),
        "row_number": row.row_number,
        "status": row.status,
        "sku_code": row.sku_code,
        "channel_code": row.channel_code,
        "metric_code": row.metric_code,
        "external_record_key": row.external_record_key,
        "error_code": getattr(row, "error_code", "") or "",
    }


def serialize_batch(batch: IngestionBatch, *, include_rows: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "public_id": str(batch.public_id),
        "batch_key": batch.batch_key,
        "source_public_id": str(batch.source.public_id),
        "source_type": batch.source_type,
        "status": batch.status,
        "total_count": batch.total_count,
        "success_count": batch.success_count,
        "warning_count": batch.warning_count,
        "error_count": batch.error_count,
        "skipped_count": batch.skipped_count,
        "added_count": batch.added_count,
        "revision_count": batch.revision_count,
    }
    if include_rows:
        rows = IngestionRow.objects.filter(batch=batch).order_by("row_number", "id")
        payload["rows"] = [serialize_row(row) for row in rows]
    return payload


class OperatingIngestionBatchCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_batches_create",
        request=BATCH_CREATE_REQUEST,
        responses={201: BATCH_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        source_public_id = data.get("source_public_id")
        batch_key = str(data.get("batch_key") or "").strip()
        source_type = str(data.get("source_type") or "").strip()
        if not source_public_id or not batch_key or not source_type:
            raise ValidationFailedError(
                message="source_public_id, batch_key and source_type are required."
            )
        file_version = data.get("input_file_version_public_id")
        batch = CreateIngestionBatch(
            context=CommandContext.for_actor(user),
            source_public_id=UUID(str(source_public_id)),
            batch_key=batch_key,
            source_type=source_type,
            rows=list(data.get("rows") or []) or None,
            input_file_version_public_id=UUID(str(file_version)) if file_version else None,
        ).execute()
        return Response(serialize_batch(batch, include_rows=True), status=201)


class OperatingIngestionBatchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="operating_data_batches_retrieve", responses=BATCH_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = (
            IngestionBatch.objects.select_related("source")
            .filter(organization_id=user.organization_id, public_id=public_id)
            .first()
        )
        if batch is None:
            raise PermissionDeniedError()
        return Response(serialize_batch(batch, include_rows=True))


class OperatingIngestionBatchConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_batches_confirm",
        request=CONFIRM_REQUEST,
        responses={200: CONFIRM_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValidationFailedError(message="idempotency_key is required.")
        result = ConfirmOperatingIngestionBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
            idempotency_key=idempotency_key,
            confirm_warnings=bool(request.data.get("confirm_warnings")),
        ).execute()
        return Response(
            {
                "public_id": str(result.public_id),
                "added_count": result.added_count,
                "revision_count": result.revision_count,
                "skipped_count": result.skipped_count,
                "error_count": result.error_count,
                "warning_count": result.warning_count,
            }
        )


class OperatingIngestionBatchRetryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_batches_retry",
        request=None,
        responses={200: BATCH_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = RetryIngestionBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
        ).execute()
        return Response(serialize_batch(batch, include_rows=True))


class OperatingUnmappedRowsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_unmapped_list",
        responses=inline_serializer(
            name="OperatingUnmappedRowsResponse",
            fields={"items": serializers.ListField()},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        items = [
            {
                **serialize_row(row),
                "batch_public_id": str(row.batch.public_id),
                "source_public_id": str(row.batch.source.public_id),
            }
            for row in list_unmapped_ingestion_rows(user)
        ]
        return Response({"items": items})
