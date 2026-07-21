"""Operating metric definition APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from django.utils.dateparse import parse_datetime
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
from apps.operations.models import MetricDefinitionVersion
from apps.operations.queries.visible_resources import list_visible_metric_definitions
from apps.operations.services.aggregations import RecalculateMetricAggregates
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
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


def serialize_metric(metric: MetricDefinitionVersion) -> dict[str, Any]:
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


class OperatingMetricRecalculateView(APIView):
    """Thin wrapper around RecalculateMetricAggregates for E2E / ops recalculation."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_metrics_recalculate",
        request=inline_serializer(
            name="OperatingMetricRecalculateRequest",
            fields={
                "affected_keys": serializers.ListField(child=serializers.DictField()),
                "calculation_run_id": serializers.UUIDField(required=False),
            },
        ),
        responses=inline_serializer(
            name="OperatingMetricRecalculateResponse",
            fields={
                "written_count": serializers.IntegerField(),
                "calculation_run_id": serializers.UUIDField(),
            },
        ),
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        decision = authorize(
            subject_for(user),
            action="operating_fact.read",
            resource=ResourceDescriptor(
                resource_type="operating_fact",
                public_id=None,
                organization_id=user.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

        keys = list(request.data.get("affected_keys") or [])
        if not keys:
            raise ValidationFailedError(message="affected_keys is required.")
        normalized: list[dict[str, Any]] = []
        for key in keys:
            row = dict(key)
            row.setdefault("organization_id", user.organization_id)
            normalized.append(row)
        run_id = request.data.get("calculation_run_id") or uuid4()
        written = RecalculateMetricAggregates(
            calculation_run_id=UUID(str(run_id)),
            affected_keys=normalized,
        ).execute()
        return Response(
            {"written_count": written, "calculation_run_id": str(run_id)},
            status=200,
        )
