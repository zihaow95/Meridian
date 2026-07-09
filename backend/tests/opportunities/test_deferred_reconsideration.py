"""Defer, quarterly review and reconsideration flows."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.utils import timezone

from apps.configuration.models import ConfigurationVersion
from apps.identity.models.user import User
from apps.opportunities.models import (
    CandidateSource,
    CandidateStatus,
    DeferRecord,
    DeferStatus,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    QuarterlyAction,
    SourceRole,
)
from apps.opportunities.services.defer_subject import DeferSubject
from apps.opportunities.services.quarterly_review import QuarterlyReview
from apps.opportunities.services.start_reconsideration import StartReconsideration
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import GateResult, GateStatus, StageGateInstance
from apps.stage_gates.services.record_major_decision import RecordMajorGateDecision


@dataclass
class PassedOpportunityBundle:
    subject: Opportunity
    latest_review_cycle_id: int


@pytest.fixture
def passed_opportunity(review_cycle, grant_action) -> PassedOpportunityBundle:
    grant_action(
        review_cycle.subject.proposal_owner,
        "reconsideration.create",
        "opportunity",
        role_code="PROPOSER",
    )
    RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.PASSED,
        final_decision=GateResult.PASSED,
        decision_summary="Not a fit this year.",
        idempotency_key="gate-pass",
    ).execute()
    review_cycle.subject.refresh_from_db()
    review_cycle.stage_gate.refresh_from_db()
    return PassedOpportunityBundle(
        subject=review_cycle.subject,
        latest_review_cycle_id=review_cycle.stage_gate.id,
    )


@pytest.fixture
def eligible_owner(passed_opportunity: PassedOpportunityBundle) -> User:
    return passed_opportunity.subject.proposal_owner


@pytest.mark.django_db
def test_defer_accepts_restart_trigger_without_reason(review_cycle) -> None:
    record = DeferSubject(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        subject_type="OPPORTUNITY",
        subject_public_id=review_cycle.subject.public_id,
        stage_code="PROPOSAL_TO_CASE",
        defer_reason="",
        restart_trigger="Competitor launch evidence arrives.",
        next_review_quarter="2026Q4",
    ).execute()
    assert record.restart_trigger == "Competitor launch evidence arrives."
    review_cycle.subject.refresh_from_db()
    assert review_cycle.subject.proposal_status == ProposalStatus.DEFERRED


@pytest.mark.django_db
def test_deferred_gate_decision_creates_active_defer_record(review_cycle) -> None:
    RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.DEFERRED,
        final_decision=GateResult.DEFERRED,
        decision_summary="Wait for channel evidence.",
        idempotency_key="gate-defer",
        restart_trigger="Competitor launch evidence arrives.",
        next_review_quarter="2026Q4",
    ).execute()
    review_cycle.subject.refresh_from_db()
    assert review_cycle.subject.proposal_status == ProposalStatus.DEFERRED
    record = DeferRecord.objects.get(
        subject_public_id=review_cycle.subject.public_id,
        status=DeferStatus.ACTIVE,
    )
    assert record.stage_code == "PROPOSAL_TO_CASE"
    assert record.restart_trigger == "Competitor launch evidence arrives."


@pytest.mark.django_db
def test_quarterly_update_trigger_updates_active_defer_record(
    review_cycle,
    grant_action,
) -> None:
    grant_action(review_cycle.final_decision_actor, "deferred_item.review", "opportunity")
    record = RecordMajorGateDecision(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        stage_gate_public_id=review_cycle.stage_gate.public_id,
        management_conclusion=GateResult.DEFERRED,
        final_decision=GateResult.DEFERRED,
        decision_summary="Wait.",
        idempotency_key="gate-defer-review",
        restart_trigger="Old trigger.",
        next_review_quarter="2026Q3",
    ).execute()
    assert record.final_decision == GateResult.DEFERRED
    defer_record = DeferRecord.objects.get(subject_public_id=review_cycle.subject.public_id)
    QuarterlyReview(
        context=CommandContext.for_actor(review_cycle.final_decision_actor),
        defer_record_public_id=defer_record.public_id,
        action=QuarterlyAction.UPDATE_TRIGGER,
        note="Updated trigger.",
        new_restart_trigger="New trigger after channel review.",
        new_next_review_quarter="2026Q4",
    ).execute()
    defer_record.refresh_from_db()
    assert defer_record.restart_trigger == "New trigger after channel review."
    assert defer_record.next_review_quarter == "2026Q4"


@pytest.mark.django_db
def test_reconsideration_creates_new_cycle_without_editing_pass_record(
    passed_opportunity: PassedOpportunityBundle,
    eligible_owner: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    old_cycle_id = passed_opportunity.latest_review_cycle_id
    reconsideration = StartReconsideration(
        context=CommandContext.for_actor(eligible_owner),
        original_subject_public_id=passed_opportunity.subject.public_id,
        target_stage_code="PROPOSAL_TO_CASE",
        reason="New customer evidence.",
    ).execute()
    assert reconsideration.original_cycle_id == old_cycle_id
    assert reconsideration.new_cycle_id != old_cycle_id
    passed_opportunity.subject.refresh_from_db()
    assert passed_opportunity.subject.proposal_status == ProposalStatus.IN_REVIEW
    # Original pass cycle is unchanged.
    original = StageGateInstance.objects.get(id=old_cycle_id)
    assert original.status == GateStatus.DECIDED


@pytest.mark.django_db
def test_reconsideration_flags_dependent_candidates(
    organization,
    passed_opportunity: PassedOpportunityBundle,
    eligible_owner: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no="PC-FLAG",
        name="Dependent candidate",
        status=CandidateStatus.ASSESSING,
    )
    CandidateSource.objects.create(
        organization=organization,
        candidate=candidate,
        opportunity=passed_opportunity.subject,
        source_role=SourceRole.PRIMARY,
        is_active=True,
        linked_at=timezone.now(),
        linked_by=eligible_owner,
    )

    StartReconsideration(
        context=CommandContext.for_actor(eligible_owner),
        original_subject_public_id=passed_opportunity.subject.public_id,
        target_stage_code="PROPOSAL_TO_CASE",
        reason="Market changed.",
    ).execute()
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.SOURCE_RECONFIRM_REQUIRED
