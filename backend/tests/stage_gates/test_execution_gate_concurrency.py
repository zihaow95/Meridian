"""Concurrent normal gate decisions leave a single database fact."""

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
from apps.projects.models import Project
from apps.stage_gates.errors import GateAlreadyDecided
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
        department_code="CONC",
        name="Concurrency Dept",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def director(organization: Organization, grant_action) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Concurrency Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "normal_gate.decide", "stage_gate", role_code="PRODUCT_DIRECTOR")
    return user


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_decisions_leave_one_row(
    project: Project,
    department: Department,
    director: User,
) -> None:
    stage = project.stages.get(stage_code="D1")
    Task.objects.filter(project=project, stage=stage).update(status=TaskStatus.COMPLETED)
    Deliverable.objects.filter(project=project, stage=stage).update(
        status=DeliverableStatus.EXEMPTED,
        exemption_reason="ready for concurrency fixture",
        requires_professional_confirmation=False,
    )
    Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code="D1-CONC",
        name="Ready",
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
        gate = StageGateInstance.objects.create(
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
    else:
        gate.status = GateStatus.READY
        gate.save(update_fields=["status", "updated_at"])
    SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=gate.public_id,
        idempotency_key="conc-submit-file",
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
        threading.Thread(target=_decide, args=("file-conc-a",)),
        threading.Thread(target=_decide, args=("file-conc-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert any(item.startswith("ok:") for item in results)
    assert any(item.startswith("conflict:") for item in results)
    assert GateDecision.objects.filter(stage_gate=gate).count() == 1
