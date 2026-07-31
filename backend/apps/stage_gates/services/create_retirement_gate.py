"""Open the PRODUCT_RETIREMENT major stage gate for a retirement plan."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from apps.platform.application.command import CommandContext
from apps.stage_gates.models import (
    GateStatus,
    GateType,
    MaterialType,
    StageGateInstance,
    SubjectType,
)


@dataclass
class CreateRetirementGate:
    """Create the RETIREMENT_PLAN/PRODUCT_RETIREMENT stage gate instance.

    Authorization is the caller's responsibility, mirroring the
    ``open_execution_gates_for_stages`` pattern: this service assumes the
    caller already authorized the higher-level action (e.g.
    ``retirement_plan.create``) before opening the gate.
    """

    context: CommandContext
    plan_public_id: UUID
    organization_id: int

    def execute(self) -> StageGateInstance:
        return StageGateInstance.objects.create(
            organization_id=self.organization_id,
            subject_type=SubjectType.RETIREMENT_PLAN,
            subject_public_id=self.plan_public_id,
            stage_code="PRODUCT_RETIREMENT",
            cycle_number=1,
            status=GateStatus.OPEN,
            gate_type=GateType.MAJOR,
            primary_material_type=MaterialType.RETIREMENT_PLAN,
            primary_material_public_id=self.plan_public_id,
            open_material_key=f"RETIREMENT_PLAN:{self.plan_public_id}:PRODUCT_RETIREMENT:1",
        )
