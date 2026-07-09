"""MySQL-enforceable uniqueness for open stage-gate materials."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.stage_gates.material_keys import open_material_key
from apps.stage_gates.models import GateStatus, MaterialType, StageGateInstance, SubjectType


@pytest.mark.django_db
def test_duplicate_open_material_key_is_rejected(review_cycle) -> None:
    gate = review_cycle.stage_gate
    assert gate.open_material_key is not None
    with pytest.raises(IntegrityError):
        StageGateInstance.objects.create(
            organization=gate.organization,
            subject_type=SubjectType.OPPORTUNITY,
            subject_public_id=review_cycle.subject.public_id,
            stage_code=gate.stage_code,
            cycle_number=gate.cycle_number + 1,
            status=GateStatus.OPEN,
            primary_material_type=MaterialType.PROPOSAL_VERSION,
            primary_material_public_id=gate.primary_material_public_id,
            open_material_key=open_material_key(
                MaterialType.PROPOSAL_VERSION,
                gate.primary_material_public_id,
            ),
        )


@pytest.mark.django_db
def test_closed_gate_releases_open_material_key(review_cycle) -> None:
    gate = review_cycle.stage_gate
    material_key = gate.open_material_key
    gate.status = GateStatus.DECIDED
    gate.open_material_key = None
    gate.save(update_fields=["status", "open_material_key", "updated_at"])

    replacement = StageGateInstance.objects.create(
        organization=gate.organization,
        subject_type=SubjectType.OPPORTUNITY,
        subject_public_id=review_cycle.subject.public_id,
        stage_code=gate.stage_code,
        cycle_number=gate.cycle_number + 1,
        status=GateStatus.OPEN,
        primary_material_type=MaterialType.PROPOSAL_VERSION,
        primary_material_public_id=gate.primary_material_public_id,
        open_material_key=material_key,
    )
    assert replacement.open_material_key == material_key
