"""Advance project stage after an approving execution-gate decision.

Uses stage_gates models only (no stage_gates service import) to avoid a
projects ↔ stage_gates application-service cycle.
"""

from __future__ import annotations

from datetime import datetime

from apps.projects.models import Project, ProjectStage, ProjectStageStatus
from apps.stage_gates.models import GateStatus, StageGateInstance


def activate_next_stage_after_completion(
    *,
    completed_stage: ProjectStage,
    occurred_at: datetime,
) -> ProjectStage | None:
    """Activate the next stage after ``completed_stage`` and open its gate."""

    nxt = (
        ProjectStage.objects.select_for_update()
        .filter(
            project_id=completed_stage.project_id,
            sequence_no__gt=completed_stage.sequence_no,
        )
        .order_by("sequence_no")
        .first()
    )
    if nxt is None:
        return None

    nxt.status = ProjectStageStatus.ACTIVE
    nxt.actual_start_at = occurred_at
    nxt.save(update_fields=["status", "actual_start_at", "updated_at"])

    project = Project.objects.select_for_update().get(pk=completed_stage.project_id)
    project.current_stage = nxt
    project.save(update_fields=["current_stage", "updated_at"])

    if nxt.gate_code:
        gate = StageGateInstance.objects.filter(
            project=project,
            stage_code=nxt.gate_code,
            cycle_number=1,
        ).first()
        if gate is not None and gate.status == GateStatus.OPEN:
            gate.status = GateStatus.READY
            gate.project_stage = nxt
            gate.save(update_fields=["status", "project_stage", "updated_at"])
    return nxt
