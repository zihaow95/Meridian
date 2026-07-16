"""FIRST_LAUNCH gate decisions require dual authenticated conclusions and locked submit."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
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
from apps.stage_gates.services.record_first_launch_decision import (
    RecordFirstLaunchFinalDecision,
    RecordFirstLaunchManagementConclusion,
)
from tests.stage_gates.first_launch_fixtures import prepare_submitted_first_launch_gate


def _record_dual(
    *,
    management_actor: User,
    final_actor: User,
    gate: StageGateInstance,
    management_conclusion: str,
    final_decision: str,
    idempotency_key: str,
    decision_summary: str = "",
):
    RecordFirstLaunchManagementConclusion(
        context=CommandContext.for_actor(management_actor),
        stage_gate_public_id=gate.public_id,
        management_conclusion=management_conclusion,
        decision_summary=decision_summary,
        idempotency_key=f"{idempotency_key}:mgmt",
    ).execute()
    return RecordFirstLaunchFinalDecision(
        context=CommandContext.for_actor(final_actor),
        stage_gate_public_id=gate.public_id,
        final_decision=final_decision,
        decision_summary=decision_summary,
        idempotency_key=idempotency_key,
    ).execute()


@pytest.fixture
def first_launch_gate(project: Project) -> StageGateInstance:
    return prepare_submitted_first_launch_gate(project)


@pytest.fixture
def management_actor(organization, grant_action) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Launch Management",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(
        user,
        "first_launch.management_conclusion.record",
        "stage_gate",
        role_code="MANAGEMENT_COMMITTEE",
    )
    return user


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
        "first_launch.final_decision.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(user, "product.publish_new", "product", role_code="BOSS")
    return user


@pytest.mark.django_db
def test_first_launch_rejects_open_gate_without_submission(
    project: Project,
    management_actor: User,
) -> None:
    stage = project.stages.get(stage_code="L2")
    gate = StageGateInstance.objects.create(
        organization=project.organization,
        subject_type=SubjectType.PROJECT,
        subject_public_id=project.public_id,
        stage_code="FIRST_LAUNCH",
        cycle_number=99,
        status=GateStatus.OPEN,
        gate_type=GateType.MAJOR,
        project=project,
        project_stage=stage,
        primary_material_type=MaterialType.PROJECT_STAGE,
        primary_material_public_id=stage.public_id,
    )
    with pytest.raises(GateDecisionNotAllowed):
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(management_actor),
            stage_gate_public_id=gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="skip submit",
            idempotency_key="fl-open",
        ).execute()


@pytest.mark.django_db
def test_management_conclusion_denied_without_permission(
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    with pytest.raises(PermissionDeniedError):
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(launch_final_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="",
            idempotency_key="fl-deny-mgmt",
        ).execute()


@pytest.mark.django_db
def test_final_decision_denied_without_permission(
    first_launch_gate: StageGateInstance,
    management_actor: User,
) -> None:
    RecordFirstLaunchManagementConclusion(
        context=CommandContext.for_actor(management_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        decision_summary="",
        idempotency_key="fl-deny-final-mgmt",
    ).execute()
    with pytest.raises(PermissionDeniedError):
        RecordFirstLaunchFinalDecision(
            context=CommandContext.for_actor(management_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            final_decision=GateResult.APPROVED,
            decision_summary="",
            idempotency_key="fl-deny-final",
        ).execute()


@pytest.mark.django_db
def test_first_launch_requires_management_before_final(
    first_launch_gate: StageGateInstance,
    launch_final_actor: User,
) -> None:
    with pytest.raises(MajorGateConclusionRequired):
        RecordFirstLaunchFinalDecision(
            context=CommandContext.for_actor(launch_final_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            final_decision=GateResult.APPROVED,
            decision_summary="missing management",
            idempotency_key="fl-1",
        ).execute()


@pytest.mark.django_db
def test_non_approved_first_launch_does_not_publish(
    project: Project,
    first_launch_gate: StageGateInstance,
    management_actor: User,
    launch_final_actor: User,
) -> None:
    result = _record_dual(
        management_actor=management_actor,
        final_actor=launch_final_actor,
        gate=first_launch_gate,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.NEEDS_INFO,
        idempotency_key="fl-needs",
        decision_summary="Need more evidence",
    )
    project.refresh_from_db()
    first_launch_gate.refresh_from_db()
    assert result.decision.final_decision == GateResult.NEEDS_INFO
    assert result.decision.has_conclusion_difference is True
    assert result.decision.submission_id == first_launch_gate.current_submission_id
    assert project.status != ProjectStatus.OPERATING
    assert first_launch_gate.status == GateStatus.NEEDS_INFO
    assert AuditEvent.objects.filter(
        action_code="first_launch.management_conclusion.record",
        resource_public_id=first_launch_gate.public_id,
    ).exists()
    assert AuditEvent.objects.filter(
        action_code="first_launch.final_decision.record",
        resource_public_id=first_launch_gate.public_id,
    ).exists()


@pytest.mark.django_db
def test_second_first_launch_decision_rejected(
    first_launch_gate: StageGateInstance,
    management_actor: User,
    launch_final_actor: User,
) -> None:
    _record_dual(
        management_actor=management_actor,
        final_actor=launch_final_actor,
        gate=first_launch_gate,
        management_conclusion=GateResult.DEFERRED,
        final_decision=GateResult.DEFERRED,
        idempotency_key="fl-defer",
        decision_summary="Defer",
    )
    with pytest.raises(MajorGateAlreadyDecided):
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(management_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="Change mind",
            idempotency_key="fl-defer-2",
        ).execute()


@pytest.mark.django_db
def test_first_launch_rejects_non_l2_gate(
    project: Project,
    management_actor: User,
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
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(management_actor),
            stage_gate_public_id=gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="wrong gate",
            idempotency_key="fl-wrong",
        ).execute()


@pytest.mark.django_db
def test_first_launch_decision_is_idempotent(
    first_launch_gate: StageGateInstance,
    management_actor: User,
    launch_final_actor: User,
) -> None:
    first = _record_dual(
        management_actor=management_actor,
        final_actor=launch_final_actor,
        gate=first_launch_gate,
        management_conclusion=GateResult.PASSED,
        final_decision=GateResult.PASSED,
        idempotency_key="fl-pass",
        decision_summary="Passed",
    )
    second = RecordFirstLaunchFinalDecision(
        context=CommandContext.for_actor(launch_final_actor),
        stage_gate_public_id=first_launch_gate.public_id,
        final_decision=GateResult.PASSED,
        decision_summary="Passed",
        idempotency_key="fl-pass",
    ).execute()
    assert first.decision.public_id == second.decision.public_id
    assert MajorGateDecision.objects.filter(stage_gate=first_launch_gate).count() == 1


@pytest.mark.django_db(transaction=True)
def test_first_launch_management_concurrent_create_is_unique(
    first_launch_gate: StageGateInstance,
    management_actor: User,
) -> None:
    if connection.vendor == "sqlite":
        pytest.skip("MySQL uniqueness under concurrency is the gate under test.")

    def _create(key: str) -> None:
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(management_actor),
            stage_gate_public_id=first_launch_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="",
            idempotency_key=key,
        ).execute()

    _create("fl-concurrent-a")
    with pytest.raises((MajorGateAlreadyDecided, IntegrityError)):
        with transaction.atomic():
            _create("fl-concurrent-b")
    assert MajorGateDecision.objects.filter(stage_gate=first_launch_gate).count() == 1
