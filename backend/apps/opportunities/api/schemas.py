"""OpenAPI schema helpers for opportunity APIs."""

from __future__ import annotations

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

LIFECYCLE_BOARD_ITEM_SCHEMA = inline_serializer(
    name="LifecycleBoardItem",
    fields={
        "item_type": serializers.CharField(),
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "title": serializers.CharField(),
        "lifecycle_stage": serializers.CharField(),
        "status": serializers.CharField(),
        "owner_public_id": serializers.CharField(),
        "owner_display_name": serializers.CharField(),
        "candidate_public_id": serializers.CharField(allow_null=True),
        "updated_at": serializers.CharField(),
    },
)

LIFECYCLE_BOARD_PAGE_SCHEMA = inline_serializer(
    name="LifecycleBoardPage",
    fields={
        "items": serializers.ListField(child=LIFECYCLE_BOARD_ITEM_SCHEMA),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "total_count": serializers.IntegerField(),
        "has_more": serializers.BooleanField(),
    },
)

MAJOR_GATE_DECISION_REQUEST_SCHEMA = inline_serializer(
    name="MajorGateDecisionRequest",
    fields={
        "management_conclusion": serializers.CharField(),
        "final_decision": serializers.CharField(),
        "decision_summary": serializers.CharField(required=False, allow_blank=True),
        "idempotency_key": serializers.CharField(),
        "defer_reason": serializers.CharField(required=False, allow_blank=True),
        "restart_trigger": serializers.CharField(required=False, allow_blank=True),
        "next_review_quarter": serializers.CharField(required=False, allow_blank=True),
    },
)

MAJOR_GATE_DECISION_RESPONSE_SCHEMA = inline_serializer(
    name="MajorGateDecisionResponse",
    fields={
        "public_id": serializers.CharField(),
        "stage_gate_public_id": serializers.CharField(),
        "management_conclusion": serializers.CharField(),
        "final_decision": serializers.CharField(),
        "has_conclusion_difference": serializers.BooleanField(),
        "decision_summary": serializers.CharField(),
    },
)

STAGE_GATE_SUMMARY_SCHEMA = inline_serializer(
    name="StageGateSummary",
    fields={
        "public_id": serializers.CharField(),
        "stage_code": serializers.CharField(),
        "cycle_number": serializers.IntegerField(),
        "status": serializers.CharField(),
        "subject_type": serializers.CharField(),
        "subject_public_id": serializers.CharField(),
    },
)

DEFERRED_ITEM_SCHEMA = inline_serializer(
    name="DeferredItem",
    fields={
        "public_id": serializers.CharField(),
        "subject_type": serializers.CharField(),
        "subject_public_id": serializers.CharField(),
        "stage_code": serializers.CharField(),
        "defer_reason": serializers.CharField(),
        "restart_trigger": serializers.CharField(),
        "next_review_quarter": serializers.CharField(),
        "status": serializers.CharField(),
    },
)

QUARTERLY_REVIEW_REQUEST_SCHEMA = inline_serializer(
    name="QuarterlyReviewRequest",
    fields={
        "action": serializers.CharField(),
        "note": serializers.CharField(required=False, allow_blank=True),
        "new_restart_trigger": serializers.CharField(required=False, allow_blank=True),
        "new_next_review_quarter": serializers.CharField(required=False, allow_blank=True),
    },
)

QUARTERLY_REVIEW_RESPONSE_SCHEMA = inline_serializer(
    name="QuarterlyReviewResponse",
    fields={
        "public_id": serializers.CharField(),
        "action": serializers.CharField(),
        "defer_record_public_id": serializers.CharField(),
    },
)
