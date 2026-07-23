"""Operating summary query APIs."""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.queries.operating_summary import (
    OperatingSummaryResult,
    QueryProductOperatingSummary,
    QuerySkuOperatingSummary,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

SUMMARY_RESPONSE = inline_serializer(
    name="OperatingSummaryResponse",
    fields={"items": serializers.ListField()},
)


def _parse_date(raw: str | None, *, field: str) -> date:
    if not raw:
        raise ValidationFailedError(message=f"{field} is required.")
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationFailedError(message=f"Invalid {field}.")
    return parsed


def serialize_summary_result(result: OperatingSummaryResult) -> dict[str, Any]:
    items = []
    for item in result.items:
        items.append(
            {
                "grain_type": item.grain_type,
                "grain_public_id": str(item.grain_public_id),
                "channel_public_id": (
                    str(item.channel_public_id) if item.channel_public_id else None
                ),
                "metric_code": item.metric_code,
                "metric_definition_public_id": str(item.metric_definition_public_id),
                "period_start": str(item.period_start),
                "period_end": str(item.period_end),
                "period_granularity": item.period_granularity,
                "value": None if item.value is None else str(item.value),
                "status": item.status,
                "coverage_rate": str(item.coverage_rate),
                "source_count": item.source_count,
                "has_manual_value": item.has_manual_value,
                "calculated_at": (item.calculated_at.isoformat() if item.calculated_at else None),
                "contributors": item.contributors,
                "sku_breakdown": item.sku_breakdown,
            }
        )
    return {"items": items}


def _summary_params(request: Request) -> dict[str, Any]:
    metric_codes_raw = request.query_params.get("metric_codes")
    metric_codes = None
    if metric_codes_raw:
        metric_codes = [code.strip() for code in metric_codes_raw.split(",") if code.strip()]
    include_drilldown = str(request.query_params.get("include_drilldown") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    return {
        "period_start": _parse_date(request.query_params.get("period_start"), field="period_start"),
        "period_end": _parse_date(request.query_params.get("period_end"), field="period_end"),
        "period_granularity": str(request.query_params.get("period_granularity") or "").strip()
        or None,
        "metric_codes": metric_codes,
        "include_drilldown": include_drilldown,
    }


class ProductOperatingSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="products_operating_summary_retrieve",
        parameters=[
            OpenApiParameter(name="period_start", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="period_end", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="period_granularity", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="metric_codes", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="include_drilldown", type=bool, location=OpenApiParameter.QUERY),
        ],
        responses=SUMMARY_RESPONSE,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        params = _summary_params(request)
        if not params["period_granularity"]:
            raise ValidationFailedError(message="period_granularity is required.")
        result = QueryProductOperatingSummary(
            context=CommandContext.for_actor(user),
            product_public_id=public_id,
            period_start=params["period_start"],
            period_end=params["period_end"],
            period_granularity=params["period_granularity"],
            metric_codes=params["metric_codes"],
            include_drilldown=params["include_drilldown"],
        ).execute()
        return Response(serialize_summary_result(result))


class SkuOperatingSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="skus_operating_summary_retrieve",
        parameters=[
            OpenApiParameter(name="period_start", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="period_end", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="period_granularity", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="metric_codes", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="include_drilldown", type=bool, location=OpenApiParameter.QUERY),
        ],
        responses=SUMMARY_RESPONSE,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        params = _summary_params(request)
        if not params["period_granularity"]:
            raise ValidationFailedError(message="period_granularity is required.")
        result = QuerySkuOperatingSummary(
            context=CommandContext.for_actor(user),
            sku_public_id=public_id,
            period_start=params["period_start"],
            period_end=params["period_end"],
            period_granularity=params["period_granularity"],
            metric_codes=params["metric_codes"],
            include_drilldown=params["include_drilldown"],
        ).execute()
        return Response(serialize_summary_result(result))
