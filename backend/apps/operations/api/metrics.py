"""Operating metric definition APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.queries.visible_resources import list_visible_metric_definitions
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

METRIC_SCHEMA = inline_serializer(
    name="OperatingMetricDefinition",
    fields={
        "public_id": serializers.UUIDField(),
        "metric_code": serializers.CharField(),
        "name": serializers.CharField(),
        "version_number": serializers.IntegerField(),
        "status": serializers.CharField(),
        "value_type": serializers.CharField(),
        "unit": serializers.CharField(),
        "currency": serializers.CharField(),
        "calculation_type": serializers.CharField(),
    },
)

METRIC_CREATE_REQUEST = inline_serializer(
    name="OperatingMetricCreateRequest",
    fields={
        "metric_code": serializers.CharField(),
        "name": serializers.CharField(),
        "value_type": serializers.CharField(),
        "unit": serializers.CharField(),
        "currency": serializers.CharField(),
        "source_field_codes": serializers.ListField(child=serializers.CharField()),
        "calculation_type": serializers.CharField(),
        "aggregation_rule": serializers.DictField(),
        "window_definition": serializers.DictField(),
        "coverage_requirement": serializers.DictField(),
        "valid_from": serializers.CharField(),
        "valid_to": serializers.CharField(required=False, allow_null=True),
        "controlled_rule_code": serializers.CharField(required=False),
        "parameters_json": serializers.DictField(required=False),
    },
)


def serialize_metric(metric) -> dict[str, Any]:
    return {
        "public_id": str(metric.public_id),
        "metric_code": metric.metric_code,
        "name": metric.name,
        "version_number": metric.version_number,
        "status": metric.status,
        "value_type": metric.value_type,
        "unit": metric.unit,
        "currency": metric.currency,
        "calculation_type": metric.calculation_type,
    }


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    parsed = parse_datetime(str(raw))
    if parsed is None:
        raise ValidationFailedError(message="Invalid datetime value.")
    return parsed


class OperatingMetricListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_metrics_list",
        responses=inline_serializer(
            name="OperatingMetricListResponse",
            fields={"items": serializers.ListField(child=METRIC_SCHEMA)},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        items = [serialize_metric(row) for row in list_visible_metric_definitions(user)]
        return Response({"items": items})

    @extend_schema(
        operation_id="operating_metrics_create",
        request=METRIC_CREATE_REQUEST,
        responses={201: METRIC_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        required = (
            "metric_code",
            "name",
            "value_type",
            "unit",
            "currency",
            "source_field_codes",
            "calculation_type",
            "aggregation_rule",
            "window_definition",
            "coverage_requirement",
            "valid_from",
        )
        missing = [key for key in required if data.get(key) in (None, "")]
        if missing:
            raise ValidationFailedError(message=f"Missing fields: {', '.join(missing)}")
        valid_to_raw = data.get("valid_to")
        metric = CreateMetricDefinitionDraft(
            context=CommandContext.for_actor(user),
            metric_code=str(data["metric_code"]),
            name=str(data["name"]),
            value_type=str(data["value_type"]),
            unit=str(data["unit"]),
            currency=str(data["currency"]),
            source_field_codes=list(data["source_field_codes"]),
            calculation_type=str(data["calculation_type"]),
            aggregation_rule=dict(data["aggregation_rule"]),
            window_definition=dict(data["window_definition"]),
            coverage_requirement=dict(data["coverage_requirement"]),
            valid_from=_parse_dt(data["valid_from"]),
            valid_to=_parse_dt(valid_to_raw) if valid_to_raw else None,
            controlled_rule_code=str(data.get("controlled_rule_code") or ""),
            parameters_json=dict(data.get("parameters_json") or {}),
        ).execute()
        return Response(serialize_metric(metric), status=201)


class OperatingMetricPublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_metrics_publish",
        request=None,
        responses={200: METRIC_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        metric = PublishMetricDefinition(
            context=CommandContext.for_actor(user),
            metric_public_id=public_id,
        ).execute()
        return Response(serialize_metric(metric))
