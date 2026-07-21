"""Retirement plan create/validate/submit/decide/execute loop."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    VersionStatus,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.errors import RetirementSubmissionIncomplete
from apps.operations.models import (
    IssueSourceType,
    OperatingDataSnapshot,
    OperatingIssue,
    RetirementActionStatus,
    RetirementActionType,
    RetirementExecutionAction,
    RetirementPlanStatus,
)
from apps.operations.services.retirement_plans import CreateRetirementPlan, ExecuteRetirementPlan
from apps.platform.application.command import CommandContext
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import (
    SKU,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductionStatus,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)
from apps.stage_gates.errors import DualControlSeparationRequired
from apps.stage_gates.models import (
    GateResult,
    GateSubmissionMaterialReference,
    MaterialType,
)
from apps.stage_gates.services.record_retirement_decision import (
    RecordRetirementFinalDecision,
    RecordRetirementManagementConclusion,
)
from apps.stage_gates.services.submit_retirement_gate import SubmitRetirementGate
from apps.stage_gates.services.validate_retirement_submission import ValidateRetirementSubmission


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RETIRE",
        name="Retire yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
        effective_from=timezone.now() - timedelta(days=100),
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-RETIRE",
        name="Cup",
        specification="120g",
        status=SKUStatus.ACTIVE,
        production_status=ProductionStatus.IN_PRODUCTION,
    )
    channel = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    return {"product": product, "version": version, "sku": sku, "channel": channel}


def _snapshot(
    organization, active_user, product, *, coverage="SUFFICIENT"
) -> OperatingDataSnapshot:
    snap = OperatingDataSnapshot(
        organization=organization,
        purpose="retirement",
        scope_json={"product_public_id": str(product.public_id)},
        periods_json=[],
        metric_codes=["GROSS_SALES"],
        payload_json={
            "sales": "1000",
            "gross_margin": "0.3",
            "inventory": "200",
            "near_expiry": "10",
            "complaints": "2",
            "coverage_status": coverage,
        },
        created_by=active_user,
    )
    snap.content_hash = snap.compute_content_hash()
    snap.save()
    return snap


def _controlled_doc(organization, active_user) -> DocumentVersion:
    document = Document.objects.create(
        organization=organization,
        document_code=f"DOC-{uuid4().hex[:8].upper()}",
        title="Retirement pack",
        source="PRODUCT",
        status=DocumentStatus.ACTIVE,
    )
    file_obj = FileObject.objects.create(
        organization=organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=f"retire/{uuid4().hex}",
        size_bytes=12,
        sha256="a" * 64,
        detected_mime_type="application/pdf",
    )
    return DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_obj,
        original_filename="retire.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.CONTROLLED,
        uploaded_by=active_user,
        uploaded_at=timezone.now(),
        controlled_at=timezone.now(),
    )


def _grants(user, grant_action) -> None:
    grant_action(user, "retirement_plan.create", "retirement_plan")
    grant_action(user, "retirement_plan.submit", "retirement_plan")
    grant_action(user, "retirement_plan.execute", "retirement_plan")
    grant_action(user, "operating_issue.create", "operating_issue")
    grant_action(user, "retirement.management_conclusion.record", "stage_gate")
    grant_action(user, "retirement.final_decision.record", "stage_gate")


def _complete_plan(active_user, grant_action, catalog, organization, **overrides):
    _grants(active_user, grant_action)
    snap = _snapshot(organization, active_user, catalog["product"])
    doc = _controlled_doc(organization, active_user)
    payload = {
        "context": CommandContext.for_actor(active_user),
        "product_public_id": catalog["product"].public_id,
        "scope_snapshot": {
            "product_version_public_ids": [str(catalog["version"].public_id)],
            "sku_public_ids": [str(catalog["sku"].public_id)],
            "channel_public_ids": [str(catalog["channel"].public_id)],
        },
        "inventory_plan": {"dispose": "sell-through"},
        "supply_contract_impact": {"contracts": []},
        "customer_market_plan": {"notice": "30d"},
        "replacement_plan": {"sku": "SKU-NEXT"},
        "stop_production_at": date(2026, 1, 1),
        "stop_sale_at": date(2026, 2, 1),
        "retire_at": date(2026, 3, 1),
        "operating_snapshot_public_id": snap.public_id,
        "document_version_public_id": doc.public_id,
        "source_type": IssueSourceType.DIRECT,
        "source_materials_json": {"memo": "board"},
    }
    payload.update(overrides)
    return CreateRetirementPlan(**payload).execute()


@pytest.mark.django_db(transaction=True)
def test_create_direct_builds_lightweight_issue_and_gate(
    organization, active_user, grant_action, catalog
) -> None:
    plan = _complete_plan(active_user, grant_action, catalog, organization)
    assert plan.status == RetirementPlanStatus.DRAFT
    assert plan.stage_gate_public_id is not None
    issue = OperatingIssue.objects.get(pk=plan.issue_id)
    assert issue.source_type == IssueSourceType.DIRECT
    assert issue.status == "RETIREMENT_REVIEW"
    assert plan.scope_snapshot["sku_public_ids"]


@pytest.mark.django_db(transaction=True)
def test_validate_requires_trd_fields(
    organization, active_user, grant_action, catalog
) -> None:
    _grants(active_user, grant_action)
    plan = CreateRetirementPlan(
        context=CommandContext.for_actor(active_user),
        product_public_id=catalog["product"].public_id,
        scope_snapshot={},
        source_materials_json={"memo": "x"},
    ).execute()
    with pytest.raises(RetirementSubmissionIncomplete) as exc:
        ValidateRetirementSubmission(
            context=CommandContext.for_actor(active_user),
            plan_public_id=plan.public_id,
        ).execute()
    assert exc.value.code == "RETIREMENT_SUBMISSION_INCOMPLETE"
    assert "missing" in exc.value.details


@pytest.mark.django_db(transaction=True)
def test_submit_locks_immutable_material_hashes(
    organization, active_user, grant_action, catalog
) -> None:
    plan = _complete_plan(active_user, grant_action, catalog, organization)
    submission = SubmitRetirementGate(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        idempotency_key="retire-submit-1",
    ).execute()
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.SUBMITTED
    refs = list(GateSubmissionMaterialReference.objects.filter(submission=submission))
    types = {r.material_type for r in refs}
    assert MaterialType.RETIREMENT_PLAN in types
    assert MaterialType.OPERATING_DATA_SNAPSHOT in types
    assert MaterialType.DOCUMENT_VERSION in types
    assert all(r.content_hash for r in refs)
    old_hash = submission.content_hash
    plan.inventory_plan = {"dispose": "changed-after-submit"}
    plan.save(update_fields=["inventory_plan", "updated_at"])
    submission.refresh_from_db()
    assert submission.content_hash == old_hash


@pytest.mark.django_db(transaction=True)
def test_dual_step_decision_approves_without_executing(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _complete_plan(active_user, grant_action, catalog, organization)
    _grants(another_active_user, grant_action)
    SubmitRetirementGate(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        idempotency_key="retire-submit-2",
    ).execute()
    RecordRetirementManagementConclusion(
        context=CommandContext.for_actor(active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        management_conclusion=GateResult.APPROVED,
        decision_summary="Mgmt ok",
        idempotency_key="mgmt-1",
    ).execute()
    with pytest.raises(DualControlSeparationRequired):
        RecordRetirementFinalDecision(
            context=CommandContext.for_actor(active_user),
            stage_gate_public_id=plan.stage_gate_public_id,
            final_decision=GateResult.APPROVED,
            decision_summary="same actor",
            idempotency_key="final-bad",
        ).execute()
    result = RecordRetirementFinalDecision(
        context=CommandContext.for_actor(another_active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        final_decision=GateResult.APPROVED,
        decision_summary="Boss ok",
        idempotency_key="final-1",
    ).execute()
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
    assert plan.approved_at is not None
    assert RetirementExecutionAction.objects.filter(plan=plan).count() == 3
    assert OutboxEvent.objects.filter(event_type="retirement.approved").count() == 1
    catalog["sku"].refresh_from_db()
    assert catalog["sku"].production_status == ProductionStatus.IN_PRODUCTION
    assert result.decision.final_decision == GateResult.APPROVED


@pytest.mark.django_db(transaction=True)
def test_execute_due_actions_and_complete(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _complete_plan(active_user, grant_action, catalog, organization)
    _grants(another_active_user, grant_action)
    SubmitRetirementGate(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        idempotency_key="retire-submit-3",
    ).execute()
    RecordRetirementManagementConclusion(
        context=CommandContext.for_actor(active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        management_conclusion=GateResult.APPROVED,
        decision_summary="Mgmt ok",
        idempotency_key="mgmt-2",
    ).execute()
    RecordRetirementFinalDecision(
        context=CommandContext.for_actor(another_active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        final_decision=GateResult.APPROVED,
        decision_summary="Boss ok",
        idempotency_key="final-2",
    ).execute()
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
    assert RetirementExecutionAction.objects.filter(plan=plan).count() == 3

    # Before dates: no mutation
    early = ExecuteRetirementPlan(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        as_of=date(2025, 12, 1),
    ).execute()
    assert early.status == RetirementPlanStatus.EXECUTING
    catalog["sku"].refresh_from_db()
    assert catalog["sku"].production_status == ProductionStatus.IN_PRODUCTION

    executed = ExecuteRetirementPlan(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        as_of=date(2026, 3, 1),
    ).execute()
    assert executed.status == RetirementPlanStatus.COMPLETED
    plan.refresh_from_db()
    catalog["sku"].refresh_from_db()
    catalog["channel"].refresh_from_db()
    catalog["product"].refresh_from_db()
    catalog["version"].refresh_from_db()
    assert plan.status == RetirementPlanStatus.COMPLETED
    assert catalog["sku"].production_status == ProductionStatus.STOPPED
    assert catalog["sku"].status == SKUStatus.INACTIVE
    assert catalog["channel"].channel_status == ChannelStatus.OFF_SALE
    assert catalog["product"].lifecycle_status == ProductLifecycleStatus.RETIRED
    assert catalog["version"].status == ProductVersionStatus.INACTIVE
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.COMPLETED
        ).count()
        == 3
    )

    # Replay does not reopen completed actions
    ExecuteRetirementPlan(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        as_of=date(2026, 3, 1),
    ).execute()
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, action_type=RetirementActionType.RETIRE
        ).count()
        == 1
    )
