"""Minimal OpenAPI schemas for phase-4 execution APIs."""

from __future__ import annotations

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

PROJECT_LIST_ITEM = inline_serializer(
    name="ProjectListItem",
    fields={
        "public_id": serializers.UUIDField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "project_type": serializers.CharField(),
        "status": serializers.CharField(),
        "leader_public_id": serializers.UUIDField(),
        "current_stage_code": serializers.CharField(allow_null=True),
    },
)

PROJECT_LIST_RESPONSE = inline_serializer(
    name="ProjectListResponse",
    fields={
        "items": serializers.ListField(child=PROJECT_LIST_ITEM),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "count": serializers.IntegerField(),
    },
)

PROJECT_DETAIL_RESPONSE = inline_serializer(
    name="ProjectWorkbenchDetail",
    fields={
        "public_id": serializers.UUIDField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "project_type": serializers.CharField(),
        "status": serializers.CharField(),
        "candidate_public_id": serializers.UUIDField(allow_null=True),
        "leader_public_id": serializers.UUIDField(),
        "deputy_leader_public_id": serializers.UUIDField(allow_null=True),
        "product_asset_public_id": serializers.UUIDField(allow_null=True),
        "product_draft_public_id": serializers.UUIDField(allow_null=True),
        "current_stage_code": serializers.CharField(allow_null=True),
        "opportunity_sources": serializers.ListField(),
    },
)

ITEMS_RESPONSE = inline_serializer(
    name="WorkbenchItemsResponse",
    fields={"items": serializers.ListField()},
)

IDEMPOTENT_RESULT_REQUEST = inline_serializer(
    name="IdempotentResultRequest",
    fields={
        "result": serializers.CharField(required=False),
        "idempotency_key": serializers.CharField(),
        "decision_summary": serializers.CharField(required=False),
        "exception_rationale": serializers.CharField(required=False),
        "management_conclusion": serializers.CharField(required=False),
        "final_decision": serializers.CharField(required=False),
    },
)

PUBLIC_ID_STATUS = inline_serializer(
    name="PublicIdStatusResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(required=False),
        "result": serializers.CharField(required=False),
        "version_no": serializers.IntegerField(required=False),
    },
)
