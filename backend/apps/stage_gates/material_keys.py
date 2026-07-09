"""Helpers for MySQL-enforceable uniqueness of open stage-gate materials."""

from __future__ import annotations

from uuid import UUID

from apps.stage_gates.models import GateStatus, StageGateInstance


def open_material_key(material_type: str, material_public_id: UUID) -> str:
    return f"{material_type}:{material_public_id}"


def open_material_key_for_gate(gate: StageGateInstance) -> str | None:
    if gate.status != GateStatus.OPEN:
        return None
    return open_material_key(gate.primary_material_type, gate.primary_material_public_id)


def close_gate_material_lock(gate: StageGateInstance) -> None:
    gate.open_material_key = None
