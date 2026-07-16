"""Normal execution gate decisions (EXE-007)."""

from __future__ import annotations

import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import Project, ProjectStageStatus
from apps.stage_gates.errors import GateAlreadyDecided, GateDecisionNotAllowed
from apps.stage_gates.models import (
    GateDecision,
    GateResult,
    GateStatus,
    StageGateInstance,
    SubjectType,
)
from apps.stage_gates.services.record_normal_decision import RecordNormalGateDecision
from apps.stage_gates.services.submit_execution_gate import SubmitExecutionGate
from apps.work_items.models import (
    Deliverable,
    DeliverableStatus,
    Task,
    TaskStatus,
)


@pytest.fixture
def department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="NDEC",
        name="Normal Decision Dept",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def director(organization: Organization, grant_action) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Gate Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "normal_gate.decide", "stage_gate", role_code="PRODUCT_DIRECTOR")
    return user


def _ready_gate(project: Project, department: Department) -> StageGateInstance:
    stage = project.stages.get(stage_code="D1")
    Task.objects.filter(project=project, stage=stage).update(status=TaskStatus.COMPLETED)
    Deliverable.objects.filter(project=project, stage=stage).update(
        status=DeliverableStatus.EXEMPTED,
        exemption_reason="ok",
        requires_professional_confirmation=False,
    )
    Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code="D1-RDY",
        name="Ready core",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=department,
        status=TaskStatus.COMPLETED,
        version_no=1,
    )
    gate = StageGateInstance.objects.filter(
        project=project,
        stage_code="D1_GATE",
        cycle_number=1,
    ).first()
    if gate is None:
        return StageGateInstance.objects.create(
            organization=project.organization,
            subject_type=SubjectType.PROJECT,
            subject_public_id=project.public_id,
            stage_code="D1_GATE",
            cycle_number=1,
            status=GateStatus.READY,
            gate_type="NORMAL",
            project=project,
            project_stage=stage,
            primary_material_type="PROJECT_STAGE",
            primary_material_public_id=stage.public_id,
        )
    gate.status = GateStatus.READY
    gate.project_stage = stage
    gate.save(update_fields=["status", "project_stage", "updated_at"])
    return gate


@pytest.mark.django_db
def test_approved_with_exception_requires_director(
    project: Project,
    department: Department,
) -> None:
    gate = _ready_gate(project, department)
    SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=gate.public_id,
        idempotency_key="exc-submit",
    ).execute()
    with pytest.raises((PermissionDeniedError, GateDecisionNotAllowed)):
        RecordNormalGateDecision(
            context=CommandContext.for_actor(project.leader),
            stage_gate_public_id=gate.public_id,
            result=GateResult.APPROVED_WITH_EXCEPTION,
            decision_summary="Exception pass",
            idempotency_key="exc-decide",
            exception_rationale="Ship with known gap",
        ).execute()


@pytest.mark.django_db
def test_director_approved_with_exception_completes_stage(
    project: Project,
    department: Department,
    director: User,
) -> None:
    gate = _ready_gate(project, department)
    SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=gate.public_id,
        idempotency_key="exc-submit-2",
    ).execute()
    decision = RecordNormalGateDecision(
        context=CommandContext.for_actor(director),
        stage_gate_public_id=gate.public_id,
        result=GateResult.APPROVED_WITH_EXCEPTION,
        decision_summary="Exception pass",
        idempotency_key="exc-decide-2",
        exception_rationale="Ship with known gap",
    ).execute()
    assert decision.decision.result == GateResult.APPROVED_WITH_EXCEPTION
    stage = project.stages.get(stage_code="D1")
    stage.refresh_from_db()
    assert stage.status == ProjectStageStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_concurrent_normal_decisions_leave_one_fact(
    project: Project,
    department: Department,
    director: User,
) -> None:
    gate = _ready_gate(project, department)
    SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=gate.public_id,
        idempotency_key="conc-submit",
    ).execute()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def _decide(key: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            RecordNormalGateDecision(
                context=CommandContext.for_actor(director),
                stage_gate_public_id=gate.public_id,
                result=GateResult.APPROVED,
                decision_summary="approve",
                idempotency_key=key,
            ).execute()
            results.append(f"ok:{key}")
        except (GateAlreadyDecided, PermissionDeniedError):
            results.append(f"conflict:{key}")
        except Exception as exc:  # noqa: BLE001
            results.append(f"error:{type(exc).__name__}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_decide, args=("conc-a",)),
        threading.Thread(target=_decide, args=("conc-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert any(item.startswith("ok:") for item in results)
    assert any(item.startswith("conflict:") for item in results)
    assert GateDecision.objects.filter(stage_gate=gate).count() == 1
