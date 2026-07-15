"""PublishAndHandover after approved FIRST_LAUNCH (EXE-010)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.db import DatabaseError
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.operations.models import MonitoringScope
from apps.platform.application.command import CommandContext
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductVersion,
)
from apps.projects.models import Project, ProjectStatus
from apps.projects.services.publish_and_handover import PublishAndHandover
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    GateType,
    MaterialType,
    StageGateInstance,
    SubjectType,
)
from apps.stage_gates.services.record_first_launch_decision import RecordFirstLaunchDecision
from tests.products.schema_factories import build_published_product_schema


@pytest.fixture
def published_product_schema(organization: Organization, project: Project) -> object:
    product = project.product_asset
    assert product is not None
    product.category_code = "YOGURT"
    product.save(update_fields=["category_code", "updated_at"])
    return build_published_product_schema(organization=organization, category_code="YOGURT")


def _prepare_publishable_draft(project: Project, actor: User) -> ProductChangeSet:
    draft = project.product_draft
    assert draft is not None
    draft.change_scope = {
        "effective_from": timezone.now().isoformat(),
        "skus": [
            {
                "sku_code": "SKU-LAUNCH",
                "name": "Launch cup",
                "barcode": "6900000000200",
                "specification": "120g",
            }
        ],
        "channels": [
            {
                "sku_code": "SKU-LAUNCH",
                "channel_code": "TMALL",
                "channel_status": "ON_SALE",
            }
        ],
    }
    draft.status = ChangeSetStatus.APPROVED
    draft.approved_by = actor
    draft.change_type = ChangeSetType.NEW_PRODUCT
    draft.save(
        update_fields=["change_scope", "status", "approved_by", "change_type", "updated_at"]
    )
    product = draft.product
    product.category_code = product.category_code or "YOGURT"
    product.save(update_fields=["category_code", "updated_at"])
    return draft


@pytest.fixture
def first_launch_gate(project: Project) -> StageGateInstance:
    stage = project.stages.get(stage_code="L2")
    return StageGateInstance.objects.create(
        organization=project.organization,
        subject_type=SubjectType.PROJECT,
        subject_public_id=project.public_id,
        stage_code="FIRST_LAUNCH",
        cycle_number=1,
        status=GateStatus.SUBMITTED,
        gate_type=GateType.MAJOR,
        project=project,
        project_stage=stage,
        primary_material_type=MaterialType.PROJECT_STAGE,
        primary_material_public_id=stage.public_id,
    )


@pytest.fixture
def launch_final_actor(organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Handover Boss",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    for action in (
        "first_launch.management_conclusion.record",
        "first_launch.final_decision.record",
        "product.publish_new",
    ):
        resource = "product" if action.startswith("product.") else "stage_gate"
        grant_action(user, action, resource, role_code="BOSS")
    return user


@pytest.fixture
def repair_director(organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Repair Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "product.publish_new", "product", role_code="PRODUCT_DIRECTOR")
    return user


@pytest.mark.django_db(transaction=True)
def test_approved_first_launch_publishes_and_hands_over(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
    published_product_schema,
) -> None:
    del published_product_schema
    _prepare_publishable_draft(project, launch_final_actor)
    result = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Launch approved",
        idempotency_key="fl-approve",
    ).execute()
    project.refresh_from_db()
    draft = project.product_draft
    assert draft is not None
    draft.refresh_from_db()
    assert result.decision.final_decision == GateResult.APPROVED
    assert draft.status == ChangeSetStatus.PUBLISHED
    assert ProductVersion.objects.filter(change_set=draft).count() == 1
    assert MonitoringScope.objects.filter(project=project).count() == 1
    assert project.status == ProjectStatus.OPERATING
    assert project.product_asset.lifecycle_status == ProductLifecycleStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_publish_failure_keeps_decision_and_enters_repair(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
    published_product_schema,
    monkeypatch,
) -> None:
    del published_product_schema
    draft = _prepare_publishable_draft(project, launch_final_actor)
    before_primary = draft.product.primary_version_id

    def _boom(*_args, **_kwargs):
        raise DatabaseError("simulated publish failure")

    monkeypatch.setattr(
        "apps.products.services.publish_change_set.create_channel_configurations",
        _boom,
    )
    result = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Launch approved",
        idempotency_key="fl-fail",
    ).execute()
    project.refresh_from_db()
    draft.refresh_from_db()
    draft.product.refresh_from_db()
    assert result.decision.public_id is not None
    assert project.status == ProjectStatus.PUBLISH_PENDING_REPAIR
    assert draft.status == ChangeSetStatus.APPROVED
    assert draft.product.primary_version_id == before_primary
    assert MonitoringScope.objects.filter(project=project).count() == 0
    assert result.handover_error == "PRODUCT_PUBLICATION_FAILED"


@pytest.mark.django_db(transaction=True)
def test_repair_retry_publishes_idempotently(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
    repair_director: User,
    published_product_schema,
    monkeypatch,
) -> None:
    del published_product_schema
    draft = _prepare_publishable_draft(project, launch_final_actor)
    calls = {"fail": True}
    import apps.products.services.publish_change_set as publish_mod

    real_create = publish_mod.create_channel_configurations

    def _maybe_boom(*args, **kwargs):
        if calls["fail"]:
            raise DatabaseError("simulated publish failure")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(publish_mod, "create_channel_configurations", _maybe_boom)
    decision_result = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Launch approved",
        idempotency_key="fl-retry-base",
    ).execute()
    assert decision_result.handover_error == "PRODUCT_PUBLICATION_FAILED"
    calls["fail"] = False

    first = PublishAndHandover(
        context=CommandContext.for_actor(repair_director),
        project_public_id=project.public_id,
        decision_public_id=decision_result.decision.public_id,
        idempotency_key=f"{decision_result.decision.public_id}:{draft.public_id}",
    ).execute()
    second = PublishAndHandover(
        context=CommandContext.for_actor(repair_director),
        project_public_id=project.public_id,
        decision_public_id=decision_result.decision.public_id,
        idempotency_key=f"{decision_result.decision.public_id}:{draft.public_id}",
    ).execute()
    project.refresh_from_db()
    assert first.product_version is not None
    assert first.product_version.public_id == second.product_version.public_id
    assert ProductVersion.objects.filter(change_set=draft).count() == 1
    assert MonitoringScope.objects.filter(project=project).count() == 1
    assert project.status == ProjectStatus.OPERATING
