"""Concurrent retirement final decisions yield one approved plan fact."""

from __future__ import annotations

import threading
from datetime import date
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    VersionStatus,
)
from apps.identity.models.user import User, UserStatus
from apps.operations.models import (
    IssueSourceType,
    OperatingDataSnapshot,
    RetirementPlanStatus,
)
from apps.operations.services.retirement_plans import CreateRetirementPlan
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
from apps.stage_gates.models import GateResult, MajorGateDecision
from apps.stage_gates.services.record_retirement_decision import (
    RecordRetirementFinalDecision,
    RecordRetirementManagementConclusion,
)
from apps.stage_gates.services.submit_retirement_gate import SubmitRetirementGate


def _setup(organization, active_user, another_active_user, grant_action):
    for user in (active_user, another_active_user):
        for action, resource in [
            ("retirement_plan.create", "retirement_plan"),
            ("retirement_plan.submit", "retirement_plan"),
            ("operating_issue.create", "operating_issue"),
            ("retirement.management_conclusion.record", "stage_gate"),
            ("retirement.final_decision.record", "stage_gate"),
        ]:
            grant_action(user, action, resource)
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RET-CONC",
        name="Conc retire",
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
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-RET-CONC",
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
    snap = OperatingDataSnapshot(
        organization=organization,
        purpose="retirement",
        scope_json={"product_public_id": str(product.public_id)},
        periods_json=[],
        metric_codes=[],
        payload_json={
            "sales": "1",
            "gross_margin": "1",
            "inventory": "1",
            "near_expiry": "1",
            "complaints": "1",
            "coverage_status": "SUFFICIENT",
        },
        created_by=active_user,
    )
    snap.content_hash = snap.compute_content_hash()
    snap.save()
    document = Document.objects.create(
        organization=organization,
        document_code=f"DOC-{uuid4().hex[:8].upper()}",
        title="Pack",
        source="PRODUCT",
        status=DocumentStatus.ACTIVE,
    )
    file_obj = FileObject.objects.create(
        organization=organization,
        object_key=f"k/{uuid4().hex}",
        size_bytes=1,
        sha256="b" * 64,
        detected_mime_type="application/pdf",
        storage_backend=StorageBackend.NAS_NFS,
    )
    doc = DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_obj,
        original_filename="a.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.CONTROLLED,
        uploaded_by=active_user,
        uploaded_at=timezone.now(),
        controlled_at=timezone.now(),
    )
    plan = CreateRetirementPlan(
        context=CommandContext.for_actor(active_user),
        product_public_id=product.public_id,
        scope_snapshot={
            "product_version_public_ids": [str(version.public_id)],
            "sku_public_ids": [str(sku.public_id)],
            "channel_public_ids": [str(channel.public_id)],
        },
        inventory_plan={"a": 1},
        supply_contract_impact={"a": 1},
        customer_market_plan={"a": 1},
        replacement_plan={"a": 1},
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 2, 1),
        retire_at=date(2026, 3, 1),
        operating_snapshot_public_id=snap.public_id,
        document_version_public_id=doc.public_id,
        source_type=IssueSourceType.DIRECT,
        source_materials_json={"memo": "x"},
    ).execute()
    SubmitRetirementGate(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        idempotency_key="conc-submit",
    ).execute()
    RecordRetirementManagementConclusion(
        context=CommandContext.for_actor(active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        management_conclusion=GateResult.APPROVED,
        decision_summary="ok",
        idempotency_key="conc-mgmt",
    ).execute()
    return plan


@pytest.mark.django_db(transaction=True)
def test_concurrent_final_decision_one_winner(
    organization, active_user, another_active_user, grant_action
) -> None:
    plan = _setup(organization, active_user, another_active_user, grant_action)
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []
    lock = threading.Lock()

    def _run(user: User, key: str) -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            result = RecordRetirementFinalDecision(
                context=CommandContext.for_actor(user),
                stage_gate_public_id=plan.stage_gate_public_id,
                final_decision=GateResult.APPROVED,
                decision_summary="boss",
                idempotency_key=key,
            ).execute()
            with lock:
                results.append(result)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_run, args=(another_active_user, "final-a"))
    third = User.objects.create_user(
        organization=organization,
        display_name="Third",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(third, "retirement.final_decision.record", "stage_gate")
    t2 = threading.Thread(target=_run, args=(third, "final-b"))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
    assert (
        MajorGateDecision.objects.filter(stage_gate__public_id=plan.stage_gate_public_id).count()
        == 1
    )
    assert OutboxEvent.objects.filter(event_type="retirement.approved").count() == 1
    assert len(results) >= 1
    # One may succeed; the other may raise already decided / immutable final
    assert len(results) + len(errors) == 2
