"""Phase 2 opportunity permission actions must be seeded by migration."""

from __future__ import annotations

import pytest

from apps.authorization.models.role import PermissionAction


@pytest.mark.django_db
def test_phase_2_actions_are_seeded() -> None:
    required = {
        "opportunity.create",
        "opportunity.edit",
        "opportunity.submit",
        "opportunity.withdraw",
        "opportunity.full.read",
        "opportunity.public_summary.read",
        "opportunity.export",
        "opportunity.member.invite",
        "opportunity.member.manage",
        "candidate.create",
        "candidate.combine",
        "candidate.split",
        "candidate.leadership.assign",
        "candidate.assessment.edit",
        "candidate.submit_review",
        "major_gate.management_conclusion.record",
        "major_gate.final_decision.record",
        "deferred_item.review",
        "reconsideration.create",
    }
    seeded = set(PermissionAction.objects.values_list("action_code", flat=True))
    assert required <= seeded
