"""Manual operating value override APIs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.operations.services.effective_values import (
    CreateManualEffectiveValue,
    RevokeManualEffectiveValue,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

VALUE_SCHEMA = inline_serializer(
    name="OperatingManualValue",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "numeric_value": serializers.CharField(allow_null=True),
        "reason": serializers.CharField(),
        "sku_public_id": serializers.UUIDField(),
        "channel_public_id": serializers.UUIDField(),
        "metric_definition_public_id": serializers.UUIDField(),
        "period_start": serializers.DateField(),
        "period_end": serializers.DateField(),
        "period_granularity": serializers.CharField(),
    },
)

VALUE_CREATE_REQUEST = inline_serializer(
    name="OperatingManualValueCreateRequest",
    fields={
        "sku_public_id": serializers.UUIDField(),
        "channel_public_id": serializers.UUIDField(),
        "metric_definition_public_id": serializers.UUIDField(),
        "period_granularity": serializers.CharField(),
        "period_start": serializers.CharField(),
        "period_end": serializers.CharField(),
        "numeric_value": serializers.CharField(),
        "reason": serializers.CharField(),
        "text_value": serializers.CharField(required=False),
    },
)

REVOKE_REQUEST = inline_serializer(
    name="OperatingManualValueRevokeRequest",
    fields={"reason": serializers.CharField()},
)


def serialize_manual_value(value) -> dict[str, Any]:
    return {
        "public_id": str(value.public_id),
        "status": value.status,
        "numeric_value": None if value.numeric_value is None else str(value.numeric_value),
        "reason": value.reason,
        "sku_public_id": str(value.sku.public_id),
        "channel_public_id": str(value.channel.public_id),
        "metric_definition_public_id": str(value.metric_definition.public_id),
        "period_start": str(value.period_start),
        "period_end": str(value.period_end),
        "period_granularity": value.period_granularity,
    }


def _parse_date(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    parsed = parse_date(str(raw))
    if parsed is None:
        raise ValidationFailedError(message="Invalid date value.")
    return parsed


class OperatingValueOverrideCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_values_overrides_create",
        request=VALUE_CREATE_REQUEST,
        responses={201: VALUE_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        required = (
            "sku_public_id",
            "channel_public_id",
            "metric_definition_public_id",
            "period_granularity",
            "period_start",
            "period_end",
            "numeric_value",
            "reason",
        )
        missing = [key for key in required if data.get(key) in (None, "")]
        if missing:
            raise ValidationFailedError(message=f"Missing fields: {', '.join(missing)}")
        try:
            numeric_value = Decimal(str(data["numeric_value"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValidationFailedError(message="numeric_value must be a decimal string.") from exc
        value = CreateManualEffectiveValue(
            context=CommandContext.for_actor(user),
            sku_public_id=UUID(str(data["sku_public_id"])),
            channel_public_id=UUID(str(data["channel_public_id"])),
            metric_definition_public_id=UUID(str(data["metric_definition_public_id"])),
            period_granularity=str(data["period_granularity"]),
            period_start=_parse_date(data["period_start"]),
            period_end=_parse_date(data["period_end"]),
            numeric_value=numeric_value,
            reason=str(data["reason"]),
            text_value=str(data.get("text_value") or ""),
        ).execute()
        return Response(serialize_manual_value(value), status=201)


class OperatingValueOverrideRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_values_overrides_revoke",
        request=REVOKE_REQUEST,
        responses={200: VALUE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationFailedError(message="reason is required.")
        value = RevokeManualEffectiveValue(
            context=CommandContext.for_actor(user),
            manual_value_public_id=public_id,
            reason=reason,
        ).execute()
        return Response(serialize_manual_value(value))
