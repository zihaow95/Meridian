"""Execution gate validation and immutable submissions (EXE-007)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    GateSubmission,
    StageGateInstance,
    SubjectType,
)
from apps.stage_gates.services.submit_execution_gate import SubmitExecutionGate
from apps.stage_gates.services.validate_execution_gate import ValidateExecutionGate
from apps.work_items.models import (
    Deliverable,
    DeliverableStatus,
    DeliverableTier,
    Task,
    TaskStatus,
)


@pytest.fixture
def department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="GATE",
        name="Gate Dept",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


def _complete_stage_work_items(project: Project, stage_code: str = "D1") -> None:
    stage = project.stages.get(stage_code=stage_code)
    Task.objects.filter(project=project, stage=stage).update(status=TaskStatus.COMPLETED)
    Deliverable.objects.filter(project=project, stage=stage).update(
        status=DeliverableStatus.EXEMPTED,
        exemption_reason="fixture ready",
        requires_professional_confirmation=False,
    )


def _d1_execution_gate(project: Project) -> StageGateInstance:
    stage = project.stages.get(stage_code="D1")
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


@pytest.fixture
def execution_gate(project: Project) -> StageGateInstance:
    return _d1_execution_gate(project)


@pytest.fixture
def incomplete_core_task(project: Project, department: Department) -> Task:
    return Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-GATE-CORE",
        name="Core unfinished",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=department,
        status=TaskStatus.IN_PROGRESS,
        version_no=1,
    )


@pytest.mark.django_db
def test_validate_blocks_incomplete_core_task(
    project: Project,
    execution_gate: StageGateInstance,
    incomplete_core_task: Task,
) -> None:
    result = ValidateExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=execution_gate.public_id,
    ).execute()
    codes = {item["code"] for item in result.blocks}
    assert "CORE_TASK_INCOMPLETE" in codes


@pytest.mark.django_db
def test_submit_locks_snapshot_and_new_revision_does_not_pollute(
    project: Project,
    execution_gate: StageGateInstance,
    department: Department,
    active_user: User,
) -> None:
    _complete_stage_work_items(project)
    Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-DONE",
        name="Done core",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=department,
        status=TaskStatus.COMPLETED,
        version_no=1,
    )
    deliverable = Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        deliverable_code="D1-DEL",
        name="Core del",
        tier=DeliverableTier.CORE_REQUIRED,
        status=DeliverableStatus.EXEMPTED,
        requires_professional_confirmation=False,
        exemption_reason="reuse",
    )
    digest = hashlib.sha256(b"v1").hexdigest()
    file_object = FileObject.objects.create(
        organization=project.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=f"objects/{digest}.pdf",
        size_bytes=2,
        sha256=digest,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    document = Document.objects.create(
        organization=project.organization,
        document_code=f"DOC-{uuid4().hex[:8]}",
        title="Gate file",
        source=DocumentSource.PROJECT,
        status=DocumentStatus.ACTIVE,
    )
    version = DocumentVersion.objects.create(
        organization=project.organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename="a.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.DRAFT,
        uploaded_by=active_user,
        uploaded_at=timezone.now(),
    )

    submission = SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=execution_gate.public_id,
        idempotency_key="gate-submit-1",
    ).execute()
    assert submission.submission_number == 1
    assert execution_gate.__class__.objects.get(pk=execution_gate.pk).status == GateStatus.SUBMITTED
    locked_hash = submission.snapshot_json["deliverables"][0]["status"]

    deliverable.status = DeliverableStatus.DRAFT
    deliverable.save(update_fields=["status", "updated_at"])
    submission.refresh_from_db()
    assert submission.snapshot_json["deliverables"][0]["status"] == locked_hash
    assert version.public_id  # document remains independent
    assert GateSubmission.objects.filter(stage_gate=execution_gate).count() == 1


@pytest.mark.django_db
def test_needs_info_creates_next_submission(
    project: Project,
    execution_gate: StageGateInstance,
    department: Department,
) -> None:
    from apps.stage_gates.services.record_normal_decision import RecordNormalGateDecision

    _complete_stage_work_items(project)
    Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-DONE2",
        name="Done",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=department,
        status=TaskStatus.COMPLETED,
        version_no=1,
    )
    Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        deliverable_code="D1-DEL2",
        name="Exempted",
        tier=DeliverableTier.CORE_REQUIRED,
        status=DeliverableStatus.EXEMPTED,
        requires_professional_confirmation=False,
        exemption_reason="ok",
    )
    first = SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=execution_gate.public_id,
        idempotency_key="gate-submit-a",
    ).execute()
    RecordNormalGateDecision(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=execution_gate.public_id,
        result=GateResult.NEEDS_INFO,
        decision_summary="Need more data",
        idempotency_key="gate-decide-a",
    ).execute()
    second = SubmitExecutionGate(
        context=CommandContext.for_actor(project.leader),
        stage_gate_public_id=execution_gate.public_id,
        idempotency_key="gate-submit-b",
    ).execute()
    assert first.submission_number == 1
    assert second.submission_number == 2
