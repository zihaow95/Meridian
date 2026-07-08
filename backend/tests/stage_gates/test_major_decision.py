"""Major gate decision records both conclusions; final decision drives flow."""

from __future__ import annotations

import pytest

from apps.opportunities.models import ProposalStatus
from apps.platform.application.command import CommandContext
from apps.stage_gates.errors import MajorGateAlreadyDecided
from apps.stage_gates.models import GateResult, GateStatus, MajorGateDecision
from apps.stage_gates.services.record_major_decision import RecordMajorGateDecision


@pytest.mark.django_db
def test_final_decision_controls_proposal_to_case_state(review_cycle) -> None:
    decision = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.NEEDS_INFO,
        decision_summary="Boss requires more evidence.",
        idempotency_key="gate-1",
    ).execute()

    review_cycle.subject.refresh_from_db()
    assert decision.has_conclusion_difference is True
    assert review_cycle.subject.proposal_status == ProposalStatus.NEEDS_INFO


@pytest.mark.django_db
def test_approved_final_decision_moves_proposal_into_case(review_cycle) -> None:
    decision = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Approved.",
        idempotency_key="gate-1",
    ).execute()

    review_cycle.subject.refresh_from_db()
    review_cycle.stage_gate.refresh_from_db()
    assert decision.has_conclusion_difference is False
    assert review_cycle.subject.proposal_status == ProposalStatus.CASE_APPROVED
    assert review_cycle.stage_gate.status == GateStatus.DECIDED


@pytest.mark.django_db
def test_repeated_decision_with_same_key_is_idempotent(review_cycle) -> None:
    first = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Approved.",
        idempotency_key="gate-1",
    ).execute()
    second = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Approved.",
        idempotency_key="gate-1",
    ).execute()
    assert first.public_id == second.public_id
    assert MajorGateDecision.objects.filter(stage_gate=review_cycle.stage_gate).count() == 1


@pytest.mark.django_db
def test_second_distinct_decision_is_rejected(review_cycle) -> None:
    RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.APPROVED,
        final_decision=GateResult.APPROVED,
        decision_summary="Approved.",
        idempotency_key="gate-1",
    ).execute()
    with pytest.raises(MajorGateAlreadyDecided):
        RecordMajorGateDecision(
            context=CommandContext.for_actor(review_cycle.final_decision_actor),
            stage_gate_public_id=review_cycle.stage_gate.public_id,
            management_conclusion=GateResult.APPROVED,
            final_decision=GateResult.PASSED,
            decision_summary="Changed my mind.",
            idempotency_key="gate-2",
        ).execute()
