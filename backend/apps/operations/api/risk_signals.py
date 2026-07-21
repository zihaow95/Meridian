"""Risk signal APIs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.models import RiskSignal
from apps.operations.queries.visible_resources import list_visible_risk_signals
from apps.operations.services.operating_issues import EscalateRiskSignal
from apps.operations.services.risk_signals import CloseRiskSignal, MarkRiskSignalViewed
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

SIGNAL_SCHEMA = inline_serializer(
    name="RiskSignal",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "scope_type": serializers.CharField(),
        "scope_id": serializers.UUIDField(),
        "scope_key": serializers.CharField(),
        "period_start": serializers.DateField(),
        "period_end": serializers.DateField(),
        "period_granularity": serializers.CharField(),
        "coverage_status": serializers.CharField(),
        "actual_value": serializers.CharField(allow_null=True),
        "threshold_value": serializers.CharField(allow_null=True),
        "rule_code": serializers.CharField(),
        "closed_reason": serializers.CharField(),
    },
)


def serialize_signal(signal: RiskSignal) -> dict[str, Any]:
    return {
        "public_id": str(signal.public_id),
        "status": signal.status,
        "scope_type": signal.scope_type,
        "scope_id": str(signal.scope_id),
        "scope_key": signal.scope_key,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
        "period_granularity": signal.period_granularity,
        "coverage_status": signal.coverage_status,
        "actual_value": None if signal.actual_value is None else str(signal.actual_value),
        "threshold_value": (
            None if signal.threshold_value is None else str(signal.threshold_value)
        ),
        "rule_code": signal.rule_version.rule_code,
        "closed_reason": signal.closed_reason,
    }


class RiskSignalListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_signals_list",
        parameters=[
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="RiskSignalListResponse",
            fields={"items": serializers.ListField(child=SIGNAL_SCHEMA)},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        status = request.query_params.get("status") or None
        items = [
            serialize_signal(row)
            for row in list_visible_risk_signals(user, status=status).select_related("rule_version")
        ]
        return Response({"items": items})


class RiskSignalViewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_signals_view",
        request=None,
        responses={200: SIGNAL_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        signal = MarkRiskSignalViewed(
            context=CommandContext.for_actor(user),
            signal_public_id=public_id,
        ).execute()
        signal = type(signal).objects.select_related("rule_version").get(pk=signal.pk)
        return Response(serialize_signal(signal))


class RiskSignalCloseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_signals_close",
        request=inline_serializer(
            name="RiskSignalCloseRequest",
            fields={"reason": serializers.CharField()},
        ),
        responses={200: SIGNAL_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationFailedError(message="reason is required.")
        signal = CloseRiskSignal(
            context=CommandContext.for_actor(user),
            signal_public_id=public_id,
            reason=reason,
        ).execute()
        signal = type(signal).objects.select_related("rule_version").get(pk=signal.pk)
        return Response(serialize_signal(signal))


class RiskSignalEscalateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="risk_signals_escalate",
        request=inline_serializer(
            name="RiskSignalEscalateRequest",
            fields={
                "title": serializers.CharField(),
                "phenomenon_summary": serializers.CharField(),
                "target_review_at": serializers.CharField(required=False, allow_null=True),
            },
        ),
        responses={
            201: inline_serializer(
                name="RiskSignalEscalateResponse",
                fields={
                    "issue_public_id": serializers.UUIDField(),
                    "title": serializers.CharField(),
                    "status": serializers.CharField(),
                },
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        title = str(request.data.get("title") or "").strip()
        summary = str(request.data.get("phenomenon_summary") or "").strip()
        if not title or not summary:
            raise ValidationFailedError(message="title and phenomenon_summary are required.")
        target_raw = request.data.get("target_review_at")
        target_review_at = parse_datetime(str(target_raw)) if target_raw else None
        issue = EscalateRiskSignal(
            context=CommandContext.for_actor(user),
            signal_public_id=public_id,
            title=title,
            phenomenon_summary=summary,
            target_review_at=target_review_at,
        ).execute()
        return Response(
            {
                "issue_public_id": str(issue.public_id),
                "title": issue.title,
                "status": issue.status,
            },
            status=201,
        )
