"""Risk rule configuration APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_date, parse_datetime
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
from apps.operations.api.pagination import PAGE_QUERY_PARAMETERS, page_params
from apps.operations.models import RiskRuleVersion
from apps.operations.queries.pagination import paginate_queryset
from apps.operations.queries.visible_resources import list_visible_risk_rules
from apps.operations.services.risk_rules import (
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext

RISK_RULE_SCHEMA = inline_serializer(
    name="RiskRuleDefinition",
    fields={
        "public_id": serializers.UUIDField(),
        "rule_code": serializers.CharField(),
        "name": serializers.CharField(),
        "version_number": serializers.IntegerField(),
        "status": serializers.CharField(),
        "evaluator_code": serializers.CharField(),
        "scope_type": serializers.CharField(),
        "metric_codes": serializers.ListField(child=serializers.CharField()),
    },
)

RISK_RULE_CREATE_REQUEST = inline_serializer(
    name="RiskRuleCreateRequest",
    fields={
        "rule_code": serializers.CharField(),
        "name": serializers.CharField(),
        "metric_codes": serializers.ListField(child=serializers.CharField()),
        "evaluator_code": serializers.CharField(),
        "parameters_json": serializers.DictField(),
        "scope_type": serializers.CharField(),
        "valid_from": serializers.CharField(),
        "valid_to": serializers.CharField(required=False, allow_null=True),
    },
)


def serialize_risk_rule(rule: RiskRuleVersion) -> dict[str, Any]:
    return {
        "public_id": str(rule.public_id),
        "rule_code": rule.rule_code,
        "name": rule.name,
        "version_number": rule.version_number,
        "status": rule.status,
        "evaluator_code": rule.evaluator_code,
        "scope_type": rule.scope_type,
        "metric_codes": list(rule.metric_codes or []),
    }


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    parsed = parse_datetime(str(raw))
    if parsed is None:
        raise ValidationFailedError(message="Invalid datetime value.")
    return parsed


class RiskRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_rules_list",
        parameters=PAGE_QUERY_PARAMETERS,
        responses=inline_serializer(
            name="RiskRuleListResponse",
            fields={
                "items": serializers.ListField(child=RISK_RULE_SCHEMA),
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "count": serializers.IntegerField(),
            },
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        page, page_size = page_params(request)
        result = paginate_queryset(list_visible_risk_rules(user), page=page, page_size=page_size)
        return Response(
            {
                "items": [serialize_risk_rule(row) for row in result.items],
                "page": result.page,
                "page_size": result.page_size,
                "count": result.count,
            }
        )

    @extend_schema(
        operation_id="risk_rules_create",
        request=RISK_RULE_CREATE_REQUEST,
        responses={201: RISK_RULE_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        required = (
            "rule_code",
            "name",
            "metric_codes",
            "evaluator_code",
            "parameters_json",
            "scope_type",
            "valid_from",
        )
        missing = [key for key in required if data.get(key) in (None, "")]
        if missing:
            raise ValidationFailedError(message=f"Missing fields: {', '.join(missing)}")
        valid_to_raw = data.get("valid_to")
        rule = CreateRiskRuleDraft(
            context=CommandContext.for_actor(user),
            rule_code=str(data["rule_code"]),
            name=str(data["name"]),
            metric_codes=list(data["metric_codes"]),
            evaluator_code=str(data["evaluator_code"]),
            parameters_json=dict(data["parameters_json"]),
            scope_type=str(data["scope_type"]),
            valid_from=_parse_dt(data["valid_from"]),
            valid_to=_parse_dt(valid_to_raw) if valid_to_raw else None,
        ).execute()
        return Response(serialize_risk_rule(rule), status=201)


class RiskRulePublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_rules_publish",
        request=None,
        responses={200: RISK_RULE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        rule = PublishRiskRule(
            context=CommandContext.for_actor(user),
            rule_public_id=public_id,
        ).execute()
        return Response(serialize_risk_rule(rule))


class RiskRuleEvaluateView(APIView):
    """Thin authenticated wrapper around EvaluateRiskRules for governed E2E/ops runs."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_rules_evaluate",
        request=inline_serializer(
            name="RiskRuleEvaluateRequest",
            fields={
                "period_granularity": serializers.CharField(),
                "period_start": serializers.CharField(),
                "period_end": serializers.CharField(),
            },
        ),
        responses=inline_serializer(
            name="RiskRuleEvaluateResponse",
            fields={
                "created_count": serializers.IntegerField(),
                "signal_public_ids": serializers.ListField(child=serializers.UUIDField()),
            },
        ),
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        decision = authorize(
            subject_for(user),
            action="risk_signal.read",
            resource=ResourceDescriptor(
                resource_type="risk_signal",
                public_id=None,
                organization_id=user.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

        data = request.data
        granularity = str(data.get("period_granularity") or "").strip()
        start_raw = data.get("period_start")
        end_raw = data.get("period_end")
        if not granularity or not start_raw or not end_raw:
            raise ValidationFailedError(
                message="period_granularity, period_start and period_end are required."
            )
        period_start = parse_date(str(start_raw))
        period_end = parse_date(str(end_raw))
        if period_start is None or period_end is None:
            raise ValidationFailedError(message="Invalid period_start or period_end.")

        signals = EvaluateRiskRules(
            rule_version_id=public_id,
            period={
                "period_granularity": granularity,
                "period_start": period_start,
                "period_end": period_end,
            },
        ).execute()
        return Response(
            {
                "created_count": len(signals),
                "signal_public_ids": [str(signal.public_id) for signal in signals],
            }
        )
