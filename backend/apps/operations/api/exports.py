"""Operating data export API."""

from __future__ import annotations

from datetime import date
from typing import cast

from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.services.exports import CreateOperatingDataExport
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

EXPORT_REQUEST = inline_serializer(
    name="OperatingDataExportRequest",
    fields={
        "period_start": serializers.CharField(),
        "period_end": serializers.CharField(),
        "period_granularity": serializers.CharField(),
        "metric_codes": serializers.ListField(child=serializers.CharField(), required=False),
    },
)

EXPORT_RESPONSE = inline_serializer(
    name="OperatingDataExportResponse",
    fields={
        "document_version_public_id": serializers.UUIDField(),
        "token": serializers.CharField(),
        "expires_at": serializers.CharField(),
    },
)


def _parse_date(raw: object, *, field: str) -> date:
    if isinstance(raw, date):
        return raw
    parsed = parse_date(str(raw or ""))
    if parsed is None:
        raise ValidationFailedError(message=f"Invalid {field}.")
    return parsed


class OperatingDataExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_exports_create",
        request=EXPORT_REQUEST,
        responses={201: EXPORT_RESPONSE},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        granularity = str(data.get("period_granularity") or "").strip()
        if not granularity:
            raise ValidationFailedError(message="period_granularity is required.")
        metric_codes = data.get("metric_codes")
        result = CreateOperatingDataExport(
            context=CommandContext.for_actor(user),
            period_start=_parse_date(data.get("period_start"), field="period_start"),
            period_end=_parse_date(data.get("period_end"), field="period_end"),
            period_granularity=granularity,
            metric_codes=list(metric_codes) if metric_codes else None,
        ).execute()
        return Response(
            {
                "document_version_public_id": str(result.document_version_public_id),
                "token": result.token,
                "expires_at": result.expires_at,
            },
            status=201,
        )
