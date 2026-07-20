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

LAUNCH_CAPABILITIES = inline_serializer(
    name="ProjectLaunchCapabilities",
    fields={
        "can_record_management_conclusion": serializers.BooleanField(),
        "can_record_final_decision": serializers.BooleanField(),
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
        "launch_capabilities": LAUNCH_CAPABILITIES,
        "can_publish_repair": serializers.BooleanField(),
    },
)

STAGE_ITEM = inline_serializer(
    name="WorkbenchStageItem",
    fields={
        "public_id": serializers.UUIDField(),
        "stage_code": serializers.CharField(),
        "name": serializers.CharField(),
        "sequence_no": serializers.IntegerField(),
        "status": serializers.CharField(),
        "gate_code": serializers.CharField(allow_null=True, required=False),
        "gate_type": serializers.CharField(allow_null=True, required=False),
        "handling_mode": serializers.CharField(allow_null=True, required=False),
        "planned_end_at": serializers.CharField(allow_null=True, required=False),
        "stage_gate_public_id": serializers.UUIDField(allow_null=True, required=False),
    },
)

TASK_ITEM = inline_serializer(
    name="WorkbenchTaskItem",
    fields={
        "public_id": serializers.UUIDField(),
        "task_code": serializers.CharField(),
        "name": serializers.CharField(),
        "stage_code": serializers.CharField(),
        "status": serializers.CharField(),
        "is_core": serializers.BooleanField(),
        "version_no": serializers.IntegerField(),
        "responsible_user_public_id": serializers.UUIDField(allow_null=True),
        "responsible_department_public_id": serializers.UUIDField(),
    },
)

DELIVERABLE_ITEM = inline_serializer(
    name="WorkbenchDeliverableItem",
    fields={
        "public_id": serializers.UUIDField(),
        "deliverable_code": serializers.CharField(),
        "name": serializers.CharField(),
        "stage_code": serializers.CharField(),
        "tier": serializers.CharField(),
        "status": serializers.CharField(),
        "current_revision_public_id": serializers.UUIDField(allow_null=True),
        "document_version_public_id": serializers.UUIDField(allow_null=True),
    },
)

STAGES_RESPONSE = inline_serializer(
    name="WorkbenchStagesResponse",
    fields={
        "items": serializers.ListField(child=STAGE_ITEM),
        "page": serializers.IntegerField(required=False),
        "page_size": serializers.IntegerField(required=False),
        "count": serializers.IntegerField(required=False),
    },
)

TASKS_RESPONSE = inline_serializer(
    name="WorkbenchTasksResponse",
    fields={
        "items": serializers.ListField(child=TASK_ITEM),
        "page": serializers.IntegerField(required=False),
        "page_size": serializers.IntegerField(required=False),
        "count": serializers.IntegerField(required=False),
    },
)

DELIVERABLES_RESPONSE = inline_serializer(
    name="WorkbenchDeliverablesResponse",
    fields={
        "items": serializers.ListField(child=DELIVERABLE_ITEM),
        "page": serializers.IntegerField(required=False),
        "page_size": serializers.IntegerField(required=False),
        "count": serializers.IntegerField(required=False),
    },
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
        "management_conclusion_by_public_id": serializers.UUIDField(required=False),
    },
)

PUBLIC_ID_STATUS = inline_serializer(
    name="PublicIdStatusResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(required=False),
        "result": serializers.CharField(required=False),
        "version_no": serializers.IntegerField(required=False),
        "handover_error": serializers.CharField(required=False, allow_null=True),
    },
)

PUBLISH_REPAIR_RESPONSE = inline_serializer(
    name="ProjectPublishRepairResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "handover_error": serializers.CharField(required=False, allow_null=True),
        "product_version_public_id": serializers.UUIDField(allow_null=True),
        "monitoring_scope_public_id": serializers.UUIDField(allow_null=True),
    },
)

EMPTY_BODY_REQUEST = inline_serializer(
    name="EmptyBodyRequest",
    fields={},
)

IDEMPOTENCY_KEY_REQUEST = inline_serializer(
    name="IdempotencyKeyRequest",
    fields={"idempotency_key": serializers.CharField()},
)

MEMBER_APPOINT_REQUEST = inline_serializer(
    name="MemberAppointRequest",
    fields={
        "user_public_id": serializers.UUIDField(),
        "project_role": serializers.CharField(required=False),
    },
)

CUSTOM_TASK_CREATE_REQUEST = inline_serializer(
    name="CustomTaskCreateRequest",
    fields={
        "stage_public_id": serializers.UUIDField(),
        "task_code": serializers.CharField(),
        "name": serializers.CharField(),
        "responsible_department_public_id": serializers.UUIDField(),
        "is_core": serializers.BooleanField(required=False),
        "description": serializers.CharField(required=False),
    },
)

CUSTOM_DELIVERABLE_CREATE_REQUEST = inline_serializer(
    name="CustomDeliverableCreateRequest",
    fields={
        "stage_public_id": serializers.UUIDField(),
        "deliverable_code": serializers.CharField(),
        "name": serializers.CharField(),
        "requires_professional_confirmation": serializers.BooleanField(required=False),
    },
)

PLAN_CHANGE_REQUEST = inline_serializer(
    name="PlanChangeRequest",
    fields={
        "change_type": serializers.CharField(),
        "target_type": serializers.CharField(),
        "target_public_id": serializers.UUIDField(),
        "field_name": serializers.CharField(),
        "before_value": serializers.CharField(required=False),
        "after_value": serializers.CharField(),
        "impact_summary": serializers.CharField(required=False),
    },
)

STAGE_HANDLING_REQUEST = inline_serializer(
    name="StageHandlingRequest",
    fields={
        "requested_mode": serializers.CharField(),
        "rationale": serializers.CharField(required=False),
        "evidence_summary": serializers.CharField(required=False),
    },
)

EMERGENCY_CREATE_REQUEST = inline_serializer(
    name="EmergencyCreateRequest",
    fields={
        "subject_summary": serializers.CharField(),
        "pending_confirmation": serializers.CharField(),
        "due_at": serializers.DateTimeField(),
    },
)

EMERGENCY_COMPLETE_REQUEST = inline_serializer(
    name="EmergencyCompleteRequest",
    fields={"confirmation_summary": serializers.CharField()},
)

TASK_TRANSITION_REQUEST = inline_serializer(
    name="TaskTransitionRequest",
    fields={
        "status": serializers.CharField(),
        "version_no": serializers.IntegerField(),
    },
)

TASK_ASSIGN_REQUEST = inline_serializer(
    name="TaskAssignRequest",
    fields={
        "user_public_id": serializers.UUIDField(),
        "version_no": serializers.IntegerField(),
    },
)

FIRST_LAUNCH_MANAGEMENT_REQUEST = inline_serializer(
    name="FirstLaunchManagementRequest",
    fields={
        "management_conclusion": serializers.CharField(),
        "decision_summary": serializers.CharField(required=False),
        "idempotency_key": serializers.CharField(),
    },
)

FIRST_LAUNCH_FINAL_REQUEST = inline_serializer(
    name="FirstLaunchFinalRequest",
    fields={
        "final_decision": serializers.CharField(),
        "decision_summary": serializers.CharField(required=False),
        "idempotency_key": serializers.CharField(),
    },
)
