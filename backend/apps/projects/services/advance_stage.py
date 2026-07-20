"""Advance project stage after an approving execution-gate decision.

Owns only ``projects`` domain state (ProjectStage / Project). Opening the next
stage's gate belongs to the ``stage_gates`` domain; callers there invoke
``stage_gates.services.open_execution_gates.mark_gate_ready_for_stage`` on the
returned stage. This keeps the projects module from writing stage_gates models
and avoids a projects ↔ stage_gates application-service cycle.
"""

from __future__ import annotations

from datetime import datetime

from apps.projects.models import Project, ProjectStage, ProjectStageStatus


def activate_next_stage_after_completion(
    *,
    completed_stage: ProjectStage,
    occurred_at: datetime,
) -> ProjectStage | None:
    """Activate the next stage after ``completed_stage`` (projects domain only)."""

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
    return nxt
