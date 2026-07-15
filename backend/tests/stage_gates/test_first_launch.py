"""FIRST_LAUNCH gate decisions require dual conclusions and lock materials."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import Project, ProjectStatus
from apps.stage_gates.errors import (
    GateDecisionNotAllowed,
    MajorGateAlreadyDecided,
    MajorGateConclusionRequired,
)
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    GateType,
    MajorGateDecision,
    MaterialType,
    StageGateInstance,
    SubjectType,
)
from apps.stage_gates.services.record_first_launch_decision import RecordFirstLaunchDecision


@pytest.fixture
def first_launch_gate(project: Project) -> StageGateInstance:
    stage = project.stages.get(stage_code="L2")
    assert stage.gate_code == "FIRST_LAUNCH"
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
def launch_final_actor(organization, grant_action) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Launch Boss",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(
        user,
        "first_launch.management_conclusion.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(
        user,
        "first_launch.final_decision.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(user, "product.publish_new", "product", role_code="BOSS")
    return user


@pytest.mark.django_db
def test_first_launch_requires_both_conclusions(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    with pytest.raises(MajorGateConclusionRequired):
        RecordFirstLaunchDecision(
            context=CommandContext.for_actor(launch_final_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            management_conclusion="",
            final_decision=GateResult.APPROVED,
            decision_summary="missing management",
            idempotency_key="fl-1",
        ).execute()


@pytest.mark.django_db
def test_non_approved_first_launch_does_not_publish(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    result = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.NEEDS_INFO,
        decision_summary="Need more evidence",
        idempotency_key="fl-needs",
    ).execute()
    project.refresh_from_db()
    first_launch_gate.refresh_from_db()
    assert result.decision.final_decision == GateResult.NEEDS_INFO
    assert result.decision.has_conclusion_difference is True
    assert project.status != ProjectStatus.OPERATING
    assert first_launch_gate.status == GateStatus.NEEDS_INFO


@pytest.mark.django_db
def test_second_first_launch_decision_rejected(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.DEFERRED,
        final_decision=GateResult.DEFERRED,
        decision_summary="Defer",
        idempotency_key="fl-defer",
    ).execute()
    with pytest.raises(MajorGateAlreadyDecided):
        RecordFirstLaunchDecision(
            context=CommandContext.for_actor(launch_final_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            final_decision=GateResult.APPROVED,
            decision_summary="Change mind",
            idempotency_key="fl-defer-2",
        ).execute()


@pytest.mark.django_db
def test_first_launch_rejects_non_l2_gate(
    project: Project,
    launch_final_actor: User,
) -> None:
    stage = project.stages.get(stage_code="D1")
    gate = StageGateInstance.objects.create(
        organization=project.organization,
        subject_type=SubjectType.PROJECT,
        subject_public_id=project.public_id,
        stage_code="D1",
        cycle_number=1,
        status=GateStatus.SUBMITTED,
        gate_type=GateType.NORMAL,
        project=project,
        project_stage=stage,
        primary_material_type=MaterialType.PROJECT_STAGE,
        primary_material_public_id=stage.public_id,
    )
    with pytest.raises((GateDecisionNotAllowed, PermissionDeniedError)):
        RecordFirstLaunchDecision(
            context=CommandContext.for_actor(launch_final_actor),
            stage_gate_public_id=gate.public_id,
            management_conclusion=GateResult.APPROVED,
            final_decision=GateResult.APPROVED,
            decision_summary="wrong gate",
            idempotency_key="fl-wrong",
        ).execute()


@pytest.mark.django_db
def test_first_launch_decision_is_idempotent(
    project: Project,
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    first = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.PASSED,
        final_decision=GateResult.PASSED,
        decision_summary="Passed",
        idempotency_key="fl-pass",
    ).execute()
    second = RecordFirstLaunchDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.PASSED,
        final_decision=GateResult.PASSED,
        decision_summary="Passed",
        idempotency_key="fl-pass",
    ).execute()
    assert first.decision.public_id == second.decision.public_id
    assert MajorGateDecision.objects.filter(stage_gate=first_launch_gate).count() == 1
