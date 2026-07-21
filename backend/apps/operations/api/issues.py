"""Operating issue APIs."""

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
from apps.operations.models import OperatingIssue
from apps.operations.queries.operating_issues import get_operating_issue
from apps.operations.queries.visible_resources import list_visible_operating_issues
from apps.operations.services.iteration_proposals import ConvertIssueToIterationProposal
from apps.operations.services.operating_issues import (
    CreateOperatingIssue,
    RecordOperatingIssueDecision,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

ISSUE_SCHEMA = inline_serializer(
    name="OperatingIssue",
    fields={
        "public_id": serializers.UUIDField(),
        "business_no": serializers.CharField(),
        "title": serializers.CharField(),
        "status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "product_public_id": serializers.UUIDField(),
        "phenomenon_summary": serializers.CharField(),
    },
)


def serialize_issue_brief(issue: OperatingIssue) -> dict[str, Any]:
    return {
        "public_id": str(issue.public_id),
        "business_no": issue.business_no,
        "title": issue.title,
        "status": issue.status,
        "version_no": issue.version_no,
        "product_public_id": str(issue.product.public_id),
        "phenomenon_summary": issue.phenomenon_summary,
    }


class OperatingIssueListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_issues_list",
        parameters=[
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="OperatingIssueListResponse",
            fields={"items": serializers.ListField(child=ISSUE_SCHEMA)},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        status = request.query_params.get("status") or None
        items = [
            serialize_issue_brief(row) for row in list_visible_operating_issues(user, status=status)
        ]
        return Response({"items": items})

    @extend_schema(
        operation_id="operating_issues_create",
        request=inline_serializer(
            name="OperatingIssueCreateRequest",
            fields={
                "title": serializers.CharField(),
                "product_public_id": serializers.UUIDField(),
                "phenomenon_summary": serializers.CharField(),
                "signal_public_ids": serializers.ListField(
                    child=serializers.UUIDField(), required=False
                ),
                "source_type": serializers.CharField(required=False),
                "source_materials_json": serializers.DictField(required=False),
                "target_review_at": serializers.CharField(required=False, allow_null=True),
                "owner_public_id": serializers.UUIDField(required=False, allow_null=True),
            },
        ),
        responses={201: ISSUE_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        title = str(data.get("title") or "").strip()
        summary = str(data.get("phenomenon_summary") or "").strip()
        product_public_id = data.get("product_public_id")
        if not title or not summary or not product_public_id:
            raise ValidationFailedError(
                message="title, product_public_id and phenomenon_summary are required."
            )
        target_raw = data.get("target_review_at")
        owner_raw = data.get("owner_public_id")
        issue = CreateOperatingIssue(
            context=CommandContext.for_actor(user),
            title=title,
            product_public_id=UUID(str(product_public_id)),
            phenomenon_summary=summary,
            signal_public_ids=[UUID(str(item)) for item in (data.get("signal_public_ids") or [])],
            source_type=str(data.get("source_type") or "RISK_SIGNAL"),
            source_materials_json=dict(data.get("source_materials_json") or {}),
            target_review_at=parse_datetime(str(target_raw)) if target_raw else None,
            owner_public_id=UUID(str(owner_raw)) if owner_raw else None,
        ).execute()
        return Response(serialize_issue_brief(issue), status=201)


class OperatingIssueDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_issues_decisions_create",
        request=inline_serializer(
            name="OperatingIssueDecisionRequest",
            fields={
                "version_no": serializers.IntegerField(),
                "recommendation_type": serializers.CharField(),
                "action_summary": serializers.CharField(),
                "responsible_user_public_id": serializers.UUIDField(
                    required=False, allow_null=True
                ),
                "planned_at": serializers.CharField(required=False, allow_null=True),
                "materials_snapshot_json": serializers.DictField(required=False),
                "target_status": serializers.CharField(required=False, allow_null=True),
            },
        ),
        responses={
            201: inline_serializer(
                name="OperatingIssueDecisionResponse",
                fields={
                    "public_id": serializers.UUIDField(),
                    "recommendation_type": serializers.CharField(),
                    "action_summary": serializers.CharField(),
                    "issue": serializers.DictField(),
                },
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        data = request.data
        if data.get("version_no") is None or not data.get("recommendation_type"):
            raise ValidationFailedError(message="version_no and recommendation_type are required.")
        planned_raw = data.get("planned_at")
        responsible_raw = data.get("responsible_user_public_id")
        decision = RecordOperatingIssueDecision(
            context=CommandContext.for_actor(user),
            issue_public_id=public_id,
            version_no=int(data["version_no"]),
            recommendation_type=str(data["recommendation_type"]),
            action_summary=str(data.get("action_summary") or ""),
            responsible_user_public_id=(UUID(str(responsible_raw)) if responsible_raw else None),
            planned_at=parse_datetime(str(planned_raw)) if planned_raw else None,
            materials_snapshot_json=dict(data.get("materials_snapshot_json") or {}),
            target_status=str(data["target_status"]) if data.get("target_status") else None,
        ).execute()
        issue = get_operating_issue(organization_id=user.organization_id, issue_public_id=public_id)
        return Response(
            {
                "public_id": str(decision.public_id),
                "recommendation_type": decision.recommendation_type,
                "action_summary": decision.action_summary,
                "issue": issue,
            },
            status=201,
        )


class OperatingIssueIterationProposalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_issues_iteration_proposal_create",
        request=inline_serializer(
            name="OperatingIssueIterationProposalRequest",
            fields={
                "proposal_owner_public_id": serializers.UUIDField(),
                "idempotency_key": serializers.CharField(),
                "version_no": serializers.IntegerField(required=False, allow_null=True),
            },
        ),
        responses={201: ISSUE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        owner = request.data.get("proposal_owner_public_id")
        key = str(request.data.get("idempotency_key") or "").strip()
        if not owner or not key:
            raise ValidationFailedError(
                message="proposal_owner_public_id and idempotency_key are required."
            )
        version_no = request.data.get("version_no")
        issue = ConvertIssueToIterationProposal(
            context=CommandContext.for_actor(user),
            issue_public_id=public_id,
            proposal_owner_public_id=UUID(str(owner)),
            idempotency_key=key,
            version_no=int(version_no) if version_no is not None else None,
        ).execute()
        return Response(serialize_issue_brief(issue), status=201)
