"""Open execution StageGateInstance rows from project stages / template."""

from __future__ import annotations

from typing import Any

from apps.projects.models import Project, ProjectStage, ProjectStageStatus
from apps.stage_gates.models import (
    GateStatus,
    GateType,
    MaterialType,
    StageGateInstance,
    SubjectType,
)

_SUBMITTABLE_STAGE_STATUSES = frozenset(
    {
        ProjectStageStatus.ACTIVE,
        ProjectStageStatus.READY_FOR_GATE,
    }
)


def open_execution_gates_for_stages(
    *,
    project: Project,
    stages: list[ProjectStage],
    content: dict[str, Any] | None = None,
    ready_stage_codes: set[str] | None = None,
) -> list[StageGateInstance]:
    """Create StageGateInstance rows for declared gates.

    Only stages in ``ready_stage_codes`` (default: currently ACTIVE /
    READY_FOR_GATE) receive READY status. Future stages stay OPEN so they
    cannot be submitted until the prior gate advances the stage.
    """

    if ready_stage_codes is None:
        ready_stage_codes = {
            stage.stage_code for stage in stages if stage.status in _SUBMITTABLE_STAGE_STATUSES
        }

    gate_by_stage: dict[str, dict[str, str]] = {}
    for project_stage in stages:
        if project_stage.gate_code:
            gate_by_stage[project_stage.stage_code] = {
                "gate_code": project_stage.gate_code,
                "gate_type": project_stage.gate_type or GateType.NORMAL,
            }
    for entry in (content or {}).get("gates") or []:
        stage_code = str(entry.get("stage_code") or "")
        if not stage_code:
            continue
        gate_by_stage[stage_code] = {
            "gate_code": str(entry.get("gate_code") or ""),
            "gate_type": str(entry.get("gate_type") or GateType.NORMAL),
        }

    stages_by_code = {item.stage_code: item for item in stages}
    opened: list[StageGateInstance] = []
    for stage_code, gate_meta in gate_by_stage.items():
        matched = stages_by_code.get(stage_code)
        gate_code = gate_meta.get("gate_code") or ""
        if matched is None or not gate_code:
            continue
        stage = matched
        gate_type = gate_meta.get("gate_type") or GateType.NORMAL
        initial_status = GateStatus.READY if stage_code in ready_stage_codes else GateStatus.OPEN
        instance, created = StageGateInstance.objects.get_or_create(
            subject_type=SubjectType.PROJECT,
            subject_public_id=project.public_id,
            stage_code=gate_code,
            cycle_number=1,
            defaults={
                "organization": project.organization,
                "status": initial_status,
                "gate_type": gate_type,
                "project": project,
                "project_stage": stage,
                "primary_material_type": MaterialType.PROJECT_STAGE,
                "primary_material_public_id": stage.public_id,
            },
        )
        if created:
            opened.append(instance)
            continue
        dirty = False
        if instance.project_id is None or instance.project_stage_id is None:
            instance.organization = project.organization
            instance.project = project
            instance.project_stage = stage
            instance.gate_type = gate_type
            instance.primary_material_type = MaterialType.PROJECT_STAGE
            instance.primary_material_public_id = stage.public_id
            dirty = True
        if stage_code in ready_stage_codes and instance.status == GateStatus.OPEN:
            instance.status = GateStatus.READY
            dirty = True
        if dirty:
            instance.save()
        opened.append(instance)
    return opened


def mark_gate_ready_for_stage(*, project: Project, stage: ProjectStage) -> StageGateInstance | None:
    """Promote the stage's gate instance from OPEN to READY when the stage activates."""

    if not stage.gate_code:
        return None
    gate = StageGateInstance.objects.filter(
        project=project,
        stage_code=stage.gate_code,
        cycle_number=1,
    ).first()
    if gate is None:
        return None
    if gate.status == GateStatus.OPEN:
        gate.status = GateStatus.READY
        gate.project_stage = stage
        gate.save(update_fields=["status", "project_stage", "updated_at"])
    return gate
