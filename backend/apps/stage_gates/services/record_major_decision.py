"""Record a major stage gate decision; flow follows the final decision only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.opportunities.models import CandidateStatus, Opportunity, ProjectCandidate, ProposalStatus
from apps.opportunities.services.configuration import (
    OpportunityRuleConfigurationMissing,
    get_opportunity_rule_snapshot,
)
from apps.opportunities.services.create_project_candidate import create_initial_candidate
from apps.opportunities.services.defer_records import create_defer_record
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject
from apps.stage_gates.errors import (
    MajorGateAlreadyDecided,
    MajorGateConclusionRequired,
    MajorGateMaterialChanged,
    MajorGateRoleNotConfigured,
)
from apps.stage_gates.material_keys import close_gate_material_lock
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    MajorGateDecision,
    MaterialType,
    StageGateInstance,
    SubjectType,
)

_PROPOSAL_STATUS_BY_RESULT = {
    GateResult.APPROVED: ProposalStatus.CASE_APPROVED,
    GateResult.APPROVED_WITH_EXCEPTION: ProposalStatus.CASE_APPROVED,
    GateResult.NEEDS_INFO: ProposalStatus.NEEDS_INFO,
    GateResult.DEFERRED: ProposalStatus.DEFERRED,
    GateResult.PASSED: ProposalStatus.PASSED,
}

# Final decisions that move a proposal into case and spawn a project candidate.
_APPROVING_RESULTS = frozenset({GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION})

_CANDIDATE_STATUS_BY_RESULT = {
    GateResult.APPROVED: CandidateStatus.PROJECT_CREATED,
    GateResult.APPROVED_WITH_EXCEPTION: CandidateStatus.PROJECT_CREATED,
    GateResult.NEEDS_INFO: CandidateStatus.NEEDS_INFO,
    GateResult.DEFERRED: CandidateStatus.DEFERRED,
    GateResult.PASSED: CandidateStatus.PASSED,
}


@dataclass
class RecordMajorGateDecision:
    context: CommandContext
    stage_gate_public_id: UUID
    management_conclusion: str
    final_decision: str
    decision_summary: str
    idempotency_key: str
    defer_reason: str = ""
    restart_trigger: str = ""
    next_review_quarter: str = ""

    def execute(self) -> MajorGateDecision:
        actor = self.context.actor
        now = self.context.occurred_at

        if (
            self.management_conclusion not in GateResult.values
            or self.final_decision not in GateResult.values
        ):
            raise MajorGateConclusionRequired()

        with transaction.atomic():
            stage_gate = (
                StageGateInstance.objects.select_for_update()
                .filter(
                    public_id=self.stage_gate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if stage_gate is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="major_gate.final_decision.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=stage_gate.public_id,
                    organization_id=stage_gate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            management_decision = authorize(
                subject_for(actor),
                action="major_gate.management_conclusion.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=stage_gate.public_id,
                    organization_id=stage_gate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not management_decision.allowed:
                raise PermissionDeniedError()

            existing = MajorGateDecision.objects.filter(stage_gate=stage_gate).first()
            if existing is not None:
                if existing.idempotency_key == self.idempotency_key:
                    return existing
                raise MajorGateAlreadyDecided()
            if stage_gate.status != GateStatus.OPEN:
                raise MajorGateAlreadyDecided()

            try:
                snapshot = get_opportunity_rule_snapshot(actor.organization, now)
            except OpportunityRuleConfigurationMissing as exc:
                raise MajorGateRoleNotConfigured() from exc
            if not snapshot.final_decision_roles or not snapshot.management_conclusion_roles:
                raise MajorGateRoleNotConfigured()

            subject = self._locked_subject(stage_gate)
            self._assert_material_unchanged(stage_gate, subject)

            if (
                stage_gate.subject_type == SubjectType.PROJECT_CANDIDATE
                and GateResult(self.final_decision) in _APPROVING_RESULTS
            ):
                result = ApproveAndCreateProject(
                    context=self.context,
                    candidate_public_id=stage_gate.subject_public_id,
                    idempotency_key=self.idempotency_key,
                    management_conclusion=self.management_conclusion,
                    final_decision=self.final_decision,
                    decision_summary=self.decision_summary,
                ).execute()
                return result.gate_decision

            gate_decision = MajorGateDecision.objects.create(
                organization=stage_gate.organization,
                stage_gate=stage_gate,
                management_conclusion=self.management_conclusion,
                management_conclusion_by=actor,
                final_decision=self.final_decision,
                final_decision_by=actor,
                has_conclusion_difference=(self.management_conclusion != self.final_decision),
                decision_summary=self.decision_summary,
                idempotency_key=self.idempotency_key,
                decided_at=now,
            )

            close_gate_material_lock(stage_gate)
            stage_gate.status = GateStatus.DECIDED
            stage_gate.save(update_fields=["status", "open_material_key", "updated_at"])

            self._apply_to_subject(stage_gate, subject, now)

            final_result = GateResult(self.final_decision)
            if final_result == GateResult.DEFERRED:
                create_defer_record(
                    organization=stage_gate.organization,
                    subject_type=stage_gate.subject_type,
                    subject_public_id=stage_gate.subject_public_id,
                    stage_code=stage_gate.stage_code,
                    defer_reason=self.defer_reason,
                    restart_trigger=self.restart_trigger,
                    next_review_quarter=self.next_review_quarter,
                    last_conclusion=self.final_decision,
                )
                register_outbox_event(
                    OutboxMessage(
                        event_type="subject.deferred",
                        aggregate_type=stage_gate.subject_type.lower(),
                        aggregate_id=stage_gate.subject_public_id,
                        payload={"subject_public_id": str(stage_gate.subject_public_id)},
                        occurred_at=now,
                    )
                )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="major_gate.final_decision.record",
                    resource_type="stage_gate",
                    resource_public_id=stage_gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "management_conclusion": self.management_conclusion,
                        "final_decision": self.final_decision,
                        "has_conclusion_difference": (gate_decision.has_conclusion_difference),
                    },
                    request_metadata={"idempotency_key": self.idempotency_key},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="proposal.review_decided",
                    aggregate_type="stage_gate",
                    aggregate_id=stage_gate.public_id,
                    payload={
                        "stage_gate_public_id": str(stage_gate.public_id),
                        "final_decision": self.final_decision,
                    },
                    occurred_at=now,
                )
            )

        return gate_decision

    def _locked_subject(self, stage_gate: StageGateInstance) -> Opportunity | ProjectCandidate:
        if stage_gate.subject_type == SubjectType.PROJECT_CANDIDATE:
            subject = (
                ProjectCandidate.objects.select_for_update()
                .filter(
                    public_id=stage_gate.subject_public_id,
                    organization_id=stage_gate.organization_id,
                )
                .first()
            )
            if subject is None:
                raise MajorGateMaterialChanged()
            return subject

        if stage_gate.subject_type != SubjectType.OPPORTUNITY:
            raise MajorGateMaterialChanged()
        opportunity = (
            Opportunity.objects.select_for_update()
            .select_related("current_version")
            .filter(
                public_id=stage_gate.subject_public_id,
                organization_id=stage_gate.organization_id,
            )
            .first()
        )
        if opportunity is None:
            raise MajorGateMaterialChanged()
        return opportunity

    def _assert_material_unchanged(
        self, stage_gate: StageGateInstance, subject: Opportunity | ProjectCandidate
    ) -> None:
        if stage_gate.subject_type == SubjectType.PROJECT_CANDIDATE:
            if stage_gate.primary_material_type != MaterialType.CASE_ASSESSMENT:
                raise MajorGateMaterialChanged()
            if not isinstance(subject, ProjectCandidate):
                raise MajorGateMaterialChanged()
            if stage_gate.primary_material_public_id != subject.public_id:
                raise MajorGateMaterialChanged()
            return

        if stage_gate.primary_material_type != MaterialType.PROPOSAL_VERSION:
            return
        if not isinstance(subject, Opportunity):
            raise MajorGateMaterialChanged()
        version = subject.current_version
        if version is None or version.public_id != stage_gate.primary_material_public_id:
            raise MajorGateMaterialChanged()

    def _apply_to_subject(
        self, stage_gate: StageGateInstance, subject: Opportunity | ProjectCandidate, now: datetime
    ) -> None:
        result = GateResult(self.final_decision)
        if isinstance(subject, ProjectCandidate):
            subject.status = _CANDIDATE_STATUS_BY_RESULT[result]
            subject.version_no += 1
            subject.save(update_fields=["status", "version_no", "updated_at"])
            return

        subject.proposal_status = _PROPOSAL_STATUS_BY_RESULT[result]
        subject.version_no += 1
        subject.save(update_fields=["proposal_status", "version_no", "updated_at"])

        if result in _APPROVING_RESULTS:
            create_initial_candidate(
                opportunity=subject,
                actor=self.context.actor,
                now=now,
                trace_id=self.context.trace_id,
            )
