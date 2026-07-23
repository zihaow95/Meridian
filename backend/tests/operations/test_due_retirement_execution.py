"""operations.execute_due_retirement_actions_task: real scan + execute, not a stub."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connections
from django.utils import timezone

from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.documents.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    VersionStatus,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.operations.models import (
    IssueSourceType,
    OperatingDataSnapshot,
    RetirementActionStatus,
    RetirementExecutionAction,
    RetirementPlan,
    RetirementPlanStatus,
)
from apps.operations.services.retirement_plans import CreateRetirementPlan
from apps.operations.services.system_actor import SYSTEM_EMPLOYEE_NO
from apps.operations.tasks import execute_due_retirement_actions_task
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
from apps.stage_gates.models import GateResult
from apps.stage_gates.services.record_retirement_decision import (
    RecordRetirementFinalDecision,
    RecordRetirementManagementConclusion,
)
from apps.stage_gates.services.submit_retirement_gate import SubmitRetirementGate


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no=f"PRD-DUE-{uuid4().hex[:8].upper()}",
        name="Due retire yogurt",
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
        sku_code=f"SKU-DUE-{uuid4().hex[:8].upper()}",
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


def _grants(user, grant_action) -> None:
    grant_action(user, "retirement_plan.create", "retirement_plan")
    grant_action(user, "retirement_plan.submit", "retirement_plan")
    grant_action(user, "retirement_plan.execute", "retirement_plan")
    grant_action(user, "operating_issue.create", "operating_issue")
    grant_action(user, "retirement.management_conclusion.record", "stage_gate")
    grant_action(user, "retirement.final_decision.record", "stage_gate")


@pytest.fixture(autouse=True)
def provision_retirement_system_executor(organization) -> None:
    call_command(
        "provision_retirement_system_actor",
        organization_id=organization.id,
    )


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
        object_key=f"retire-due/{uuid4().hex}",
        size_bytes=12,
        sha256="c" * 64,
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


def _approved_plan(
    active_user,
    another_active_user,
    grant_action,
    catalog,
    organization,
    *,
    stop_production_at: date,
    stop_sale_at: date,
    retire_at: date,
    idempotency_prefix: str,
) -> RetirementPlan:
    _grants(active_user, grant_action)
    _grants(another_active_user, grant_action)
    snap = OperatingDataSnapshot(
        organization=organization,
        purpose="retirement",
        scope_json={"product_public_id": str(catalog["product"].public_id)},
        periods_json=[],
        metric_codes=["GROSS_SALES"],
        payload_json={
            "sales": "1000",
            "gross_margin": "0.3",
            "inventory": "200",
            "near_expiry": "10",
            "complaints": "2",
            "coverage_status": "SUFFICIENT",
        },
        created_by=active_user,
    )
    snap.content_hash = snap.compute_content_hash()
    snap.save()
    doc = _controlled_doc(organization, active_user)
    plan = CreateRetirementPlan(
        context=CommandContext.for_actor(active_user),
        product_public_id=catalog["product"].public_id,
        scope_snapshot={
            "product_version_public_ids": [str(catalog["version"].public_id)],
            "sku_public_ids": [str(catalog["sku"].public_id)],
            "channel_public_ids": [str(catalog["channel"].public_id)],
        },
        inventory_plan={"dispose": "sell-through"},
        supply_contract_impact={"contracts": []},
        customer_market_plan={"notice": "30d"},
        replacement_plan={"sku": "SKU-NEXT"},
        stop_production_at=stop_production_at,
        stop_sale_at=stop_sale_at,
        retire_at=retire_at,
        operating_snapshot_public_id=snap.public_id,
        document_version_public_id=doc.public_id,
        source_type=IssueSourceType.DIRECT,
        source_materials_json={"memo": "board"},
    ).execute()
    SubmitRetirementGate(
        context=CommandContext.for_actor(active_user),
        plan_public_id=plan.public_id,
        idempotency_key=f"{idempotency_prefix}-submit",
    ).execute()
    RecordRetirementManagementConclusion(
        context=CommandContext.for_actor(active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        management_conclusion=GateResult.APPROVED,
        decision_summary="Mgmt ok",
        idempotency_key=f"{idempotency_prefix}-mgmt",
    ).execute()
    RecordRetirementFinalDecision(
        context=CommandContext.for_actor(another_active_user),
        stage_gate_public_id=plan.stage_gate_public_id,
        final_decision=GateResult.APPROVED,
        decision_summary="Boss ok",
        idempotency_key=f"{idempotency_prefix}-final",
    ).execute()
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
    return plan


@pytest.mark.django_db(transaction=True)
def test_task_executes_due_plans_and_is_idempotent_on_replay(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 1, 1),
        retire_at=date(2026, 1, 1),
        idempotency_prefix="due-basic",
    )

    processed = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2026-06-01"}
    ).get()
    assert processed == 1

    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.COMPLETED
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.COMPLETED
        ).count()
        == 3
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="retirement.completed",
            aggregate_id=plan.public_id,
        ).count()
        == 1
    )

    # Replay: no PENDING actions remain due, so nothing is (re)processed and
    # nothing is double-completed.
    processed_again = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2026-06-01"}
    ).get()
    assert processed_again == 0
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.COMPLETED
        ).count()
        == 3
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="retirement.completed",
            aggregate_id=plan.public_id,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_task_ignores_plans_not_yet_due(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 2, 1),
        retire_at=date(2026, 3, 1),
        idempotency_prefix="due-future",
    )

    processed = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2025-12-01"}
    ).get()
    assert processed == 0
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.PENDING
        ).count()
        == 3
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_task_runs_do_not_double_complete_a_due_plan(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    """Two 'workers' racing the beat task on the same due plan complete it exactly once."""
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 1, 1),
        retire_at=date(2026, 1, 1),
        idempotency_prefix="due-concurrent",
    )

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    results: list[int] = []
    lock = threading.Lock()

    def _run() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            result = execute_due_retirement_actions_task.apply(
                args=(), kwargs={"as_of": "2026-06-01"}
            ).get()
            with lock:
                results.append(result)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_run)
    t2 = threading.Thread(target=_run)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, errors
    # Both workers observe the plan as "processed" (ExecuteRetirementPlan is
    # idempotent and never raises for an already-completed plan); the safety
    # property under test is that the underlying actions are not
    # double-completed, asserted below via the DB state.
    assert results == [1, 1]

    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.COMPLETED
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.COMPLETED
        ).count()
        == 3
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="retirement.completed",
            aggregate_id=plan.public_id,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_failed_action_retry_does_not_duplicate_completed_action(
    organization, active_user, another_active_user, grant_action, catalog, monkeypatch
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 2, 1),
        retire_at=date(2026, 3, 1),
        idempotency_prefix="due-retry",
    )

    from apps.products.services import retirement as retirement_module

    real_execute = retirement_module.ApplyApprovedRetirementAction.execute
    calls = {"n": 0}

    def _boom_once(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated transient failure")
        return real_execute(self)

    monkeypatch.setattr(retirement_module.ApplyApprovedRetirementAction, "execute", _boom_once)

    processed = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2026-01-15"}
    ).get()
    # ExecuteRetirementPlan captures the per-action failure internally (plan
    # moves to EXECUTION_ERROR, action to FAILED) rather than raising, so the
    # task still counts the plan as processed; the failure itself is visible
    # via plan/action status and the retirement.execution_failed event below.
    assert processed == 1

    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.EXECUTION_ERROR
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.FAILED
        ).count()
        == 1
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="retirement.execution_failed", aggregate_id=plan.public_id
        ).count()
        == 1
    )

    # Retry (e.g. next beat tick): the transient failure is gone, the action
    # completes, and it is not duplicated.
    processed_retry = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2026-01-15"}
    ).get()
    assert processed_retry == 1

    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.EXECUTING
    assert (
        RetirementExecutionAction.objects.filter(
            plan=plan, status=RetirementActionStatus.COMPLETED
        ).count()
        == 1
    )
    assert RetirementExecutionAction.objects.filter(plan=plan).count() == 3


@pytest.mark.django_db(transaction=True)
def test_due_execution_succeeds_when_plan_creator_is_disabled(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 2, 1),
        retire_at=date(2026, 3, 1),
        idempotency_prefix="due-disabled",
    )
    active_user.status = UserStatus.DISABLED
    active_user.disabled_at = timezone.now()
    active_user.save(update_fields=["status", "disabled_at", "updated_at"])
    RoleAssignment.objects.filter(user=active_user).update(status=AssignmentStatus.INACTIVE)

    processed = execute_due_retirement_actions_task.apply(
        args=(), kwargs={"as_of": "2026-06-01"}
    ).get()
    assert processed == 1
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_task_fails_closed_when_system_executor_missing(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 1, 1),
        retire_at=date(2026, 1, 1),
        idempotency_prefix="due-no-executor",
    )
    User.objects.filter(organization=organization, employee_no=SYSTEM_EMPLOYEE_NO).update(
        employee_no=f"RETIRED-{SYSTEM_EMPLOYEE_NO}"
    )

    with pytest.raises(RuntimeError, match="system executor"):
        execute_due_retirement_actions_task.apply(args=(), kwargs={"as_of": "2026-06-01"}).get()
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED


@pytest.mark.django_db(transaction=True)
def test_task_does_not_reactivate_disabled_system_executor(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    plan = _approved_plan(
        active_user,
        another_active_user,
        grant_action,
        catalog,
        organization,
        stop_production_at=date(2026, 1, 1),
        stop_sale_at=date(2026, 1, 1),
        retire_at=date(2026, 1, 1),
        idempotency_prefix="due-disabled-executor",
    )
    executor = User.objects.get(organization=organization, employee_no=SYSTEM_EMPLOYEE_NO)
    executor.status = UserStatus.DISABLED
    executor.disabled_at = timezone.now()
    executor.save(update_fields=["status", "disabled_at", "updated_at"])

    with pytest.raises(RuntimeError):
        execute_due_retirement_actions_task.apply(args=(), kwargs={"as_of": "2026-06-01"}).get()
    executor.refresh_from_db()
    assert executor.status == UserStatus.DISABLED
    plan.refresh_from_db()
    assert plan.status == RetirementPlanStatus.APPROVED
