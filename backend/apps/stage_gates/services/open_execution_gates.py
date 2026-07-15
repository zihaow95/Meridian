"""Open execution StageGateInstance rows from project stages / template."""

from __future__ import annotations

from typing import Any

from apps.projects.models import Project, ProjectStage
from apps.stage_gates.models import (
    GateStatus,
    GateType,
    MaterialType,
    StageGateInstance,
    SubjectType,
)


def open_execution_gates_for_stages(
    *,
    project: Project,
    stages: list[ProjectStage],
    content: dict[str, Any] | None = None,
) -> list[StageGateInstance]:
    """Create READY StageGateInstance for each stage that declares a gate.

    Prefer per-stage ``gate`` metadata; also honor top-level ``gates`` entries.
    Idempotent on (subject, stage_code, cycle_number=1).
    """

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
        instance, _ = StageGateInstance.objects.get_or_create(
            subject_type=SubjectType.PROJECT,
            subject_public_id=project.public_id,
            stage_code=gate_code,
            cycle_number=1,
            defaults={
                "organization": project.organization,
                "status": GateStatus.READY,
                "gate_type": gate_type,
                "project": project,
                "project_stage": stage,
                "primary_material_type": MaterialType.PROJECT_STAGE,
                "primary_material_public_id": stage.public_id,
            },
        )
        if instance.project_id is None or instance.project_stage_id is None:
            instance.organization = project.organization
            instance.project = project
            instance.project_stage = stage
            instance.gate_type = gate_type
            instance.primary_material_type = MaterialType.PROJECT_STAGE
            instance.primary_material_public_id = stage.public_id
            if instance.status not in {GateStatus.DECIDED, GateStatus.APPROVED}:
                instance.status = GateStatus.READY
            instance.save()
        opened.append(instance)
    return opened
