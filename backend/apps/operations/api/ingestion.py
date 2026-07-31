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
from apps.integrations.services.ingestion import (
    CreateIngestionBatch,
    RetryIngestionBatch,
    ValidateIngestionBatch,
)
from apps.operations.api.pagination import PAGE_QUERY_PARAMETERS, page_params
from apps.operations.queries.pagination import paginate_queryset
from apps.operations.queries.visible_resources import (
    get_visible_ingestion_batch,
    list_unmapped_ingestion_rows,
    list_visible_ingestion_batch_rows,
)
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
        "rows_url": serializers.CharField(),
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


def serialize_batch(batch: IngestionBatch) -> dict[str, Any]:
    """Return batch stats only; row detail must use the paginated rows endpoint."""

    return {
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
        "rows_url": f"/api/v1/operating-data/batches/{batch.public_id}/rows",
    }


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
        return Response(serialize_batch(batch), status=201)


class OperatingIngestionBatchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="operating_data_batches_retrieve", responses=BATCH_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = get_visible_ingestion_batch(user, public_id)
        if batch is None:
            raise PermissionDeniedError()
        return Response(serialize_batch(batch))


class OperatingIngestionBatchRowsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_batches_rows_list",
        parameters=PAGE_QUERY_PARAMETERS,
        responses=inline_serializer(
            name="OperatingIngestionBatchRowsResponse",
            fields={
                "items": serializers.ListField(),
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "count": serializers.IntegerField(),
            },
        ),
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        rows = list_visible_ingestion_batch_rows(user, public_id)
        if rows is None:
            raise PermissionDeniedError()
        page, page_size = page_params(request)
        result = paginate_queryset(rows, page=page, page_size=page_size)
        return Response(
            {
                "items": [serialize_row(row) for row in result.items],
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )


class OperatingIngestionBatchValidateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_batches_validate",
        request=None,
        responses={200: BATCH_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = ValidateIngestionBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
        ).execute()
        return Response(serialize_batch(batch))


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
        return Response(serialize_batch(batch))


class OperatingUnmappedRowsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_unmapped_list",
        parameters=PAGE_QUERY_PARAMETERS,
        responses=inline_serializer(
            name="OperatingUnmappedRowsResponse",
            fields={
                "items": serializers.ListField(),
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "count": serializers.IntegerField(),
            },
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        page, page_size = page_params(request)
        result = paginate_queryset(
            list_unmapped_ingestion_rows(user), page=page, page_size=page_size
        )
        items = [
            {
                **serialize_row(row),
                "batch_public_id": str(row.batch.public_id),
                "source_public_id": str(row.batch.source.public_id),
            }
            for row in result.items
        ]
        return Response(
            {
                "items": items,
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )
