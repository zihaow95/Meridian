"""Helpers to put FIRST_LAUNCH into a decideable SUBMITTED + active L2 state."""

from __future__ import annotations

from django.utils import timezone

from apps.identity.models.user import User
from apps.projects.models import Project, ProjectStageStatus
from apps.stage_gates.models import (
    GateStatus,
    GateSubmission,
    GateType,
    MaterialType,
    StageGateInstance,
    SubjectType,
)


def prepare_submitted_first_launch_gate(
    project: Project,
    *,
    actor: User | None = None,
) -> StageGateInstance:
    stage = project.stages.get(stage_code="L2")
    stage.status = ProjectStageStatus.ACTIVE
    stage.actual_start_at = stage.actual_start_at or timezone.now()
    stage.save(update_fields=["status", "actual_start_at", "updated_at"])
    project.current_stage = stage
    project.save(update_fields=["current_stage", "updated_at"])

    gate = StageGateInstance.objects.filter(
        project=project,
        stage_code="FIRST_LAUNCH",
        cycle_number=1,
    ).first()
    if gate is None:
        gate = StageGateInstance.objects.create(
            organization=project.organization,
            subject_type=SubjectType.PROJECT,
            subject_public_id=project.public_id,
            stage_code="FIRST_LAUNCH",
            cycle_number=1,
            status=GateStatus.READY,
            gate_type=GateType.MAJOR,
            project=project,
            project_stage=stage,
            primary_material_type=MaterialType.PROJECT_STAGE,
            primary_material_public_id=stage.public_id,
        )
    else:
        gate.gate_type = GateType.MAJOR
        gate.project_stage = stage
        gate.status = GateStatus.READY
        gate.save(update_fields=["gate_type", "project_stage", "status", "updated_at"])

    submitter = actor or project.leader
    submission = gate.current_submission
    if submission is None:
        submission = GateSubmission.objects.create(
            organization=project.organization,
            stage_gate=gate,
            submission_number=1,
            snapshot_json={"stage_code": "L2", "gate_code": "FIRST_LAUNCH"},
            content_hash="test-first-launch-hash",
            validation_result_json={"blocks": [], "warnings": []},
            submitted_by=submitter,
            submitted_at=timezone.now(),
            idempotency_key=f"test-submit-{gate.public_id}",
        )
    gate.status = GateStatus.SUBMITTED
    gate.current_submission = submission
    gate.save(update_fields=["status", "current_submission", "updated_at"])
    return gate
