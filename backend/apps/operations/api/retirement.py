"""Retirement plan APIs."""

from __future__ import annotations

from datetime import date
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
from apps.operations.errors import RetirementExecutionFailed
from apps.operations.models import RetirementPlan, RetirementPlanStatus
from apps.operations.services.retirement_plans import (
    CreateRetirementPlan,
    ExecuteRetirementPlan,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.stage_gates.services.submit_retirement_gate import SubmitRetirementGate
from apps.stage_gates.services.validate_retirement_submission import ValidateRetirementSubmission

PLAN_SCHEMA = inline_serializer(
    name="RetirementPlan",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "product_public_id": serializers.UUIDField(),
        "issue_public_id": serializers.UUIDField(),
        "stage_gate_public_id": serializers.UUIDField(allow_null=True),
        "content_hash": serializers.CharField(),
    },
)


def serialize_plan(plan: RetirementPlan) -> dict[str, Any]:
    return {
        "public_id": str(plan.public_id),
        "status": plan.status,
        "product_public_id": str(plan.product.public_id),
        "issue_public_id": str(plan.issue.public_id),
        "stage_gate_public_id": (
            str(plan.stage_gate_public_id) if plan.stage_gate_public_id else None
        ),
        "content_hash": plan.content_hash,
    }


def _parse_optional_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    parsed = parse_date(str(raw))
    if parsed is None:
        raise ValidationFailedError(message="Invalid date value.")
    return parsed


class RetirementPlanCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="retirement_plans_create",
        request=inline_serializer(
            name="RetirementPlanCreateRequest",
            fields={
                "product_public_id": serializers.UUIDField(),
                "scope_snapshot": serializers.DictField(),
                "inventory_plan": serializers.DictField(required=False),
                "supply_contract_impact": serializers.DictField(required=False),
                "customer_market_plan": serializers.DictField(required=False),
                "replacement_plan": serializers.DictField(required=False),
                "stop_production_at": serializers.CharField(required=False, allow_null=True),
                "stop_sale_at": serializers.CharField(required=False, allow_null=True),
                "retire_at": serializers.CharField(required=False, allow_null=True),
                "issue_public_id": serializers.UUIDField(required=False, allow_null=True),
                "source_type": serializers.CharField(required=False),
                "source_materials_json": serializers.DictField(required=False),
                "coverage_gap_explanation": serializers.CharField(required=False),
                "operating_snapshot_public_id": serializers.UUIDField(
                    required=False, allow_null=True
                ),
                "document_version_public_id": serializers.UUIDField(
                    required=False, allow_null=True
                ),
            },
        ),
        responses={201: PLAN_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        product_public_id = data.get("product_public_id")
        if not product_public_id:
            raise ValidationFailedError(message="product_public_id is required.")
        issue_raw = data.get("issue_public_id")
        snapshot_raw = data.get("operating_snapshot_public_id")
        doc_raw = data.get("document_version_public_id")
        plan = CreateRetirementPlan(
            context=CommandContext.for_actor(user),
            product_public_id=UUID(str(product_public_id)),
            scope_snapshot=dict(data.get("scope_snapshot") or {}),
            inventory_plan=dict(data.get("inventory_plan") or {}),
            supply_contract_impact=dict(data.get("supply_contract_impact") or {}),
            customer_market_plan=dict(data.get("customer_market_plan") or {}),
            replacement_plan=dict(data.get("replacement_plan") or {}),
            stop_production_at=_parse_optional_date(data.get("stop_production_at")),
            stop_sale_at=_parse_optional_date(data.get("stop_sale_at")),
            retire_at=_parse_optional_date(data.get("retire_at")),
            issue_public_id=UUID(str(issue_raw)) if issue_raw else None,
            source_type=str(data.get("source_type") or "DIRECT"),
            source_materials_json=dict(data.get("source_materials_json") or {}),
            coverage_gap_explanation=str(data.get("coverage_gap_explanation") or ""),
            operating_snapshot_public_id=UUID(str(snapshot_raw)) if snapshot_raw else None,
            document_version_public_id=UUID(str(doc_raw)) if doc_raw else None,
        ).execute()
        return Response(serialize_plan(plan), status=201)


class RetirementPlanValidateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="retirement_plans_validate",
        request=None,
        responses=inline_serializer(
            name="RetirementPlanValidateResponse",
            fields={
                "ok": serializers.BooleanField(),
                "missing": serializers.ListField(),
            },
        ),
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        result = ValidateRetirementSubmission(
            context=CommandContext.for_actor(user),
            plan_public_id=public_id,
        ).execute()
        return Response(result)


class RetirementPlanSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="retirement_plans_submit",
        request=inline_serializer(
            name="RetirementPlanSubmitRequest",
            fields={"idempotency_key": serializers.CharField()},
        ),
        responses={
            201: inline_serializer(
                name="RetirementPlanSubmitResponse",
                fields={
                    "public_id": serializers.UUIDField(),
                    "submission_number": serializers.IntegerField(),
                    "content_hash": serializers.CharField(),
                },
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        key = str(request.data.get("idempotency_key") or "").strip()
        if not key:
            raise ValidationFailedError(message="idempotency_key is required.")
        submission = SubmitRetirementGate(
            context=CommandContext.for_actor(user),
            plan_public_id=public_id,
            idempotency_key=key,
        ).execute()
        return Response(
            {
                "public_id": str(submission.public_id),
                "submission_number": submission.submission_number,
                "content_hash": submission.content_hash,
            },
            status=201,
        )


class RetirementPlanExecuteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="retirement_plans_execute",
        request=inline_serializer(
            name="RetirementPlanExecuteRequest",
            fields={"as_of": serializers.CharField(required=False, allow_null=True)},
        ),
        responses={200: PLAN_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        plan = ExecuteRetirementPlan(
            context=CommandContext.for_actor(user),
            plan_public_id=public_id,
            as_of=_parse_optional_date(request.data.get("as_of")),
        ).execute()
        if plan.status == RetirementPlanStatus.EXECUTION_ERROR:
            failed_action = (
                plan.execution_actions.filter(status="FAILED").order_by("-updated_at").first()
            )
            raise RetirementExecutionFailed(
                details={
                    "plan_public_id": str(plan.public_id),
                    "action_type": failed_action.action_type if failed_action else None,
                }
            )
        return Response(serialize_plan(plan))
