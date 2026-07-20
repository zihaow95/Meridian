"""Future stage gates cannot be submitted out of order (Phase-4 P0)."""

from __future__ import annotations

import pytest

from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.stage_gates.errors import GateSubmissionBlocked
from apps.stage_gates.models import GateStatus, StageGateInstance
from apps.stage_gates.services.submit_execution_gate import SubmitExecutionGate
from apps.work_items.models import Deliverable, DeliverableStatus, Task, TaskStatus


@pytest.mark.django_db
def test_future_stage_gate_stays_open_and_cannot_be_submitted(project: Project) -> None:
    d1_gate = StageGateInstance.objects.get(project=project, stage_code="D1_GATE")
    d2_gate = StageGateInstance.objects.get(project=project, stage_code="D2_GATE")
    assert d1_gate.status == GateStatus.READY
    assert d2_gate.status == GateStatus.OPEN

    stage = project.stages.get(stage_code="D2")
    Task.objects.filter(project=project, stage=stage).update(status=TaskStatus.COMPLETED)
    Deliverable.objects.filter(project=project, stage=stage).update(
        status=DeliverableStatus.EXEMPTED,
        exemption_reason="attempt skip",
        requires_professional_confirmation=False,
    )
    d2_gate.status = GateStatus.READY
    d2_gate.save(update_fields=["status", "updated_at"])

    with pytest.raises(GateSubmissionBlocked):
        SubmitExecutionGate(
            context=CommandContext.for_actor(project.leader),
            stage_gate_public_id=d2_gate.public_id,
            idempotency_key="skip-ahead-d2",
        ).execute()
