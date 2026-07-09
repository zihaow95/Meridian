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

CASE_ASSESSMENT_SCHEMA = inline_serializer(
    name="CaseAssessment",
    fields={
        "category_code": serializers.CharField(),
        "status": serializers.CharField(),
        "conclusion": serializers.CharField(),
        "deliverable_version_public_id": serializers.CharField(allow_null=True),
    },
)

PROJECT_CANDIDATE_DETAIL_SCHEMA = inline_serializer(
    name="ProjectCandidateDetail",
    fields={
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "candidate_type": serializers.CharField(),
        "status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "case_owner_public_id": serializers.CharField(allow_null=True),
        "deputy_leader_public_id": serializers.CharField(allow_null=True),
        "proposed_schedule": serializers.JSONField(allow_null=True),
        "resource_risk_summary": serializers.CharField(allow_null=True),
        "active_stage_gate_public_id": serializers.CharField(allow_null=True),
        "assessments": serializers.ListField(child=CASE_ASSESSMENT_SCHEMA),
    },
)

ASSIGN_LEADERSHIP_REQUEST_SCHEMA = inline_serializer(
    name="AssignLeadershipRequest",
    fields={
        "version_no": serializers.IntegerField(required=False),
        "case_owner_public_id": serializers.CharField(),
        "deputy_leader_public_id": serializers.CharField(required=False, allow_null=True),
    },
)

SUBMIT_CANDIDATE_REVIEW_REQUEST_SCHEMA = inline_serializer(
    name="SubmitCandidateReviewRequest",
    fields={
        "version_no": serializers.IntegerField(required=False),
        "idempotency_key": serializers.CharField(),
        "proposed_schedule": serializers.JSONField(required=False),
        "resource_risk_summary": serializers.CharField(required=False, allow_blank=True),
    },
)

ASSESSMENT_UPDATE_REQUEST_SCHEMA = inline_serializer(
    name="AssessmentUpdateRequest",
    fields={
        "conclusion": serializers.CharField(required=False, allow_blank=True),
        "status": serializers.CharField(required=False, allow_blank=True),
        "deliverable_version_public_id": serializers.CharField(required=False, allow_null=True),
    },
)

COMBINE_SOURCES_REQUEST_SCHEMA = inline_serializer(
    name="CombineSourcesRequest",
    fields={
        "opportunity_public_ids": serializers.ListField(child=serializers.CharField()),
    },
)

SPLIT_CANDIDATE_REQUEST_SCHEMA = inline_serializer(
    name="SplitCandidateRequest",
    fields={
        "candidate_names": serializers.ListField(child=serializers.CharField()),
    },
)

CANDIDATE_SPLIT_ITEM_SCHEMA = inline_serializer(
    name="CandidateSplitItem",
    fields={
        "public_id": serializers.CharField(),
        "name": serializers.CharField(),
    },
)

CANDIDATE_SPLIT_LIST_SCHEMA = inline_serializer(
    name="CandidateSplitList",
    fields={
        "public_id": serializers.CharField(),
        "name": serializers.CharField(),
    },
    many=True,
)

RECONSIDERATION_REQUEST_SCHEMA = inline_serializer(
    name="ReconsiderationRequest",
    fields={
        "original_subject_public_id": serializers.CharField(),
        "target_stage_code": serializers.CharField(required=False),
        "reason": serializers.CharField(required=False, allow_blank=True),
    },
)

RECONSIDERATION_RESPONSE_SCHEMA = inline_serializer(
    name="ReconsiderationResponse",
    fields={
        "public_id": serializers.CharField(),
        "original_cycle_public_id": serializers.CharField(),
        "new_cycle_public_id": serializers.CharField(),
        "target_stage_code": serializers.CharField(),
    },
)

PROPOSAL_VERSION_SCHEMA = inline_serializer(
    name="ProposalVersion",
    fields={
        "public_id": serializers.CharField(),
        "version_number": serializers.IntegerField(),
        "version_status": serializers.CharField(),
        "market_analysis": serializers.CharField(),
        "core_selling_points": serializers.CharField(),
        "target_users_needs": serializers.CharField(),
        "suggested_retail_price": serializers.CharField(allow_null=True),
        "submitted_at": serializers.CharField(allow_null=True),
        "locked_at": serializers.CharField(allow_null=True),
    },
)

PROPOSAL_VERSION_LIST_SCHEMA = inline_serializer(
    name="ProposalVersionList",
    fields={
        "public_id": serializers.CharField(),
        "version_number": serializers.IntegerField(),
        "version_status": serializers.CharField(),
        "market_analysis": serializers.CharField(),
        "core_selling_points": serializers.CharField(),
        "target_users_needs": serializers.CharField(),
        "suggested_retail_price": serializers.CharField(allow_null=True),
        "submitted_at": serializers.CharField(allow_null=True),
        "locked_at": serializers.CharField(allow_null=True),
    },
    many=True,
)

OPPORTUNITY_SUMMARY_SCHEMA = inline_serializer(
    name="OpportunitySummary",
    fields={
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "title": serializers.CharField(),
        "public_summary": serializers.CharField(),
        "initial_type": serializers.CharField(),
        "proposal_status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "updated_at": serializers.CharField(),
    },
)

OPPORTUNITY_SUMMARY_LIST_SCHEMA = inline_serializer(
    name="OpportunitySummaryList",
    fields={
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "title": serializers.CharField(),
        "public_summary": serializers.CharField(),
        "initial_type": serializers.CharField(),
        "proposal_status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "updated_at": serializers.CharField(),
    },
    many=True,
)

OPPORTUNITY_DETAIL_SCHEMA = inline_serializer(
    name="OpportunityDetail",
    fields={
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "title": serializers.CharField(),
        "public_summary": serializers.CharField(),
        "initial_type": serializers.CharField(),
        "proposal_status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "updated_at": serializers.CharField(),
        "quota_owner_type": serializers.CharField(),
        "current_version": PROPOSAL_VERSION_SCHEMA,
    },
)

OPPORTUNITY_PUBLIC_SCHEMA = inline_serializer(
    name="OpportunityPublic",
    fields={
        "public_id": serializers.CharField(),
        "title": serializers.CharField(),
        "public_summary": serializers.CharField(),
        "proposal_status": serializers.CharField(),
    },
)

OPPORTUNITY_CREATE_REQUEST_SCHEMA = inline_serializer(
    name="OpportunityCreateRequest",
    fields={
        "title": serializers.CharField(),
        "initial_type": serializers.CharField(required=False),
        "public_summary": serializers.CharField(required=False, allow_blank=True),
        "quota_owner_type": serializers.CharField(required=False),
        "owner_department_id": serializers.IntegerField(required=False, allow_null=True),
        "market_analysis": serializers.CharField(required=False, allow_blank=True),
        "core_selling_points": serializers.CharField(required=False, allow_blank=True),
        "target_users_needs": serializers.CharField(required=False, allow_blank=True),
        "suggested_retail_price": serializers.CharField(required=False, allow_null=True),
    },
)

OPPORTUNITY_EDIT_REQUEST_SCHEMA = inline_serializer(
    name="OpportunityEditRequest",
    fields={
        "title": serializers.CharField(required=False),
        "public_summary": serializers.CharField(required=False, allow_blank=True),
        "market_analysis": serializers.CharField(required=False, allow_blank=True),
        "core_selling_points": serializers.CharField(required=False, allow_blank=True),
        "target_users_needs": serializers.CharField(required=False, allow_blank=True),
        "suggested_retail_price": serializers.CharField(required=False, allow_null=True),
    },
)

MEMBER_INVITATION_REQUEST_SCHEMA = inline_serializer(
    name="MemberInvitationRequest",
    fields={
        "invitee_public_id": serializers.CharField(),
        "contribution_note": serializers.CharField(required=False, allow_blank=True),
    },
)

MEMBER_INVITATION_RESPONSE_SCHEMA = inline_serializer(
    name="MemberInvitationResponse",
    fields={
        "public_id": serializers.CharField(),
        "invitation_status": serializers.CharField(),
    },
)

SUBMIT_PROPOSAL_REQUEST_SCHEMA = inline_serializer(
    name="SubmitProposalRequest",
    fields={
        "version_no": serializers.IntegerField(required=False),
        "idempotency_key": serializers.CharField(),
    },
)

WITHDRAW_PROPOSAL_REQUEST_SCHEMA = inline_serializer(
    name="WithdrawProposalRequest",
    fields={
        "version_no": serializers.IntegerField(required=False),
    },
)

PROJECT_DETAIL_SCHEMA = inline_serializer(
    name="ProjectDetail",
    fields={
        "public_id": serializers.CharField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "project_type": serializers.CharField(),
        "status": serializers.CharField(),
        "candidate_public_id": serializers.CharField(),
        "leader_public_id": serializers.CharField(),
        "deputy_leader_public_id": serializers.CharField(allow_null=True),
        "product_asset_public_id": serializers.CharField(allow_null=True),
        "product_draft_public_id": serializers.CharField(allow_null=True),
    },
)

PRODUCT_DRAFT_DETAIL_SCHEMA = inline_serializer(
    name="ProductDraftDetail",
    fields={
        "public_id": serializers.CharField(),
        "draft_type": serializers.CharField(),
        "status": serializers.CharField(),
        "title": serializers.CharField(),
        "definition_summary": serializers.CharField(),
        "product_asset_public_id": serializers.CharField(),
        "product_asset_name": serializers.CharField(),
        "target_product_asset_public_id": serializers.CharField(allow_null=True),
        "candidate_public_id": serializers.CharField(),
    },
)
