"""PRODUCT_RETIREMENT dual-step major gate decisions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.models import RetirementPlan, RetirementPlanStatus
from apps.operations.services.retirement_plans import seed_execution_actions
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.errors import (
    DualControlSeparationRequired,
    GateDecisionNotAllowed,
    MajorGateAlreadyDecided,
    MajorGateConclusionRequired,
)
from apps.stage_gates.material_keys import close_gate_material_lock
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    GateType,
    MajorGateDecision,
    StageGateInstance,
    SubjectType,
)

_APPROVING = frozenset({GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION})

_GATE_STATUS_BY_RESULT: dict[str, str] = {
    GateResult.APPROVED: GateStatus.DECIDED,
    GateResult.APPROVED_WITH_EXCEPTION: GateStatus.DECIDED,
    GateResult.NEEDS_INFO: GateStatus.NEEDS_INFO,
    GateResult.DEFERRED: GateStatus.DEFERRED,
    GateResult.PASSED: GateStatus.PASSED,
}


@dataclass(frozen=True)
class RetirementDecisionResult:
    decision: MajorGateDecision
    plan: RetirementPlan | None = None


def _load_retirement_gate(*, actor: User, stage_gate_public_id: UUID) -> StageGateInstance:
    gate = (
        StageGateInstance.objects.select_for_update()
        .select_related("current_submission")
        .filter(
            public_id=stage_gate_public_id,
            organization_id=actor.organization_id,
        )
        .first()
    )
    if gate is None:
        raise PermissionDeniedError()
    if gate.stage_code != "PRODUCT_RETIREMENT":
        raise GateDecisionNotAllowed(message="Gate is not a PRODUCT_RETIREMENT decision point.")
    if gate.gate_type != GateType.MAJOR:
        raise GateDecisionNotAllowed(message="PRODUCT_RETIREMENT requires a major gate.")
    if gate.subject_type != SubjectType.RETIREMENT_PLAN:
        raise GateDecisionNotAllowed(
            message="PRODUCT_RETIREMENT subject must be a retirement plan."
        )
    return gate


def _authorize(*, actor: User, gate: StageGateInstance, action: str) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="stage_gate",
            public_id=gate.public_id,
            organization_id=gate.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


@dataclass
class RecordRetirementManagementConclusion:
    context: CommandContext
    stage_gate_public_id: UUID
    management_conclusion: str
    decision_summary: str
    idempotency_key: str

    def execute(self) -> RetirementDecisionResult:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        if not self.management_conclusion or self.management_conclusion not in GateResult.values:
            raise MajorGateConclusionRequired()

        with transaction.atomic():
            gate = _load_retirement_gate(
                actor=actor, stage_gate_public_id=self.stage_gate_public_id
            )
            _authorize(
                actor=actor,
                gate=gate,
                action="retirement.management_conclusion.record",
            )
            existing = MajorGateDecision.objects.filter(
                organization_id=gate.organization_id,
                stage_gate=gate,
                idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None:
                return RetirementDecisionResult(decision=existing)

            if MajorGateDecision.objects.filter(stage_gate=gate).exists():
                raise MajorGateAlreadyDecided()
            if gate.status != GateStatus.SUBMITTED or gate.current_submission_id is None:
                raise GateDecisionNotAllowed(
                    message="PRODUCT_RETIREMENT requires a SUBMITTED gate with locked materials."
                )

            try:
                record = MajorGateDecision.objects.create(
                    organization=gate.organization,
                    stage_gate=gate,
                    submission=gate.current_submission,
                    management_conclusion=self.management_conclusion,
                    management_conclusion_by=actor,
                    final_decision="",
                    final_decision_by=None,
                    has_conclusion_difference=False,
                    decision_summary=self.decision_summary,
                    idempotency_key=self.idempotency_key,
                    decided_at=now,
                )
            except IntegrityError as exc:
                if MajorGateDecision.objects.filter(stage_gate=gate).exists():
                    raise MajorGateAlreadyDecided() from exc
                raise

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="retirement.management_conclusion.record",
                    resource_type="stage_gate",
                    resource_public_id=gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "management_conclusion": record.management_conclusion,
                        "decision_public_id": str(record.public_id),
                    },
                )
            )
            return RetirementDecisionResult(decision=record)


@dataclass
class RecordRetirementFinalDecision:
    context: CommandContext
    stage_gate_public_id: UUID
    final_decision: str
    decision_summary: str
    idempotency_key: str

    def execute(self) -> RetirementDecisionResult:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        if not self.final_decision or self.final_decision not in GateResult.values:
            raise MajorGateConclusionRequired()

        with transaction.atomic():
            gate = _load_retirement_gate(
                actor=actor, stage_gate_public_id=self.stage_gate_public_id
            )
            _authorize(
                actor=actor,
                gate=gate,
                action="retirement.final_decision.record",
            )

            existing = MajorGateDecision.objects.filter(
                organization_id=gate.organization_id,
                stage_gate=gate,
                idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None and existing.final_decision:
                plan = RetirementPlan.objects.filter(public_id=gate.subject_public_id).first()
                return RetirementDecisionResult(decision=existing, plan=plan)

            record = MajorGateDecision.objects.select_for_update().filter(stage_gate=gate).first()
            if record is None or not record.management_conclusion:
                raise MajorGateConclusionRequired(
                    message="Management conclusion must be recorded first."
                )
            if record.final_decision:
                plan = RetirementPlan.objects.filter(public_id=gate.subject_public_id).first()
                return RetirementDecisionResult(decision=record, plan=plan)
            if record.management_conclusion_by_id == actor.id:
                raise DualControlSeparationRequired()
            if gate.status != GateStatus.SUBMITTED or gate.current_submission_id is None:
                raise GateDecisionNotAllowed(
                    message="PRODUCT_RETIREMENT requires a SUBMITTED gate with locked materials."
                )

            record.final_decision = self.final_decision
            record.final_decision_by = actor
            record.has_conclusion_difference = record.management_conclusion != self.final_decision
            if self.decision_summary:
                record.decision_summary = self.decision_summary
            record.decided_at = now
            record.save(
                update_fields=[
                    "final_decision",
                    "final_decision_by",
                    "has_conclusion_difference",
                    "decision_summary",
                    "decided_at",
                ]
            )

            gate.status = _GATE_STATUS_BY_RESULT.get(self.final_decision, GateStatus.DECIDED)
            close_gate_material_lock(gate)
            gate.save(update_fields=["status", "open_material_key", "updated_at"])

            plan = (
                RetirementPlan.objects.select_for_update()
                .filter(
                    organization_id=gate.organization_id,
                    public_id=gate.subject_public_id,
                )
                .first()
            )
            if plan is None:
                raise PermissionDeniedError()

            if self.final_decision in _APPROVING:
                plan.status = RetirementPlanStatus.APPROVED
                plan.approved_at = now
                plan.save(update_fields=["status", "approved_at", "updated_at"])
                seed_execution_actions(plan=plan)
                register_outbox_event(
                    OutboxMessage(
                        event_type="retirement.approved",
                        aggregate_type="retirement_plan",
                        aggregate_id=plan.public_id,
                        payload={
                            "plan_public_id": str(plan.public_id),
                            "stage_gate_public_id": str(gate.public_id),
                            "final_decision": self.final_decision,
                        },
                        occurred_at=now,
                    )
                )
            elif self.final_decision == GateResult.PASSED:
                plan.status = RetirementPlanStatus.PASSED
                plan.save(update_fields=["status", "updated_at"])
            elif self.final_decision == GateResult.NEEDS_INFO:
                plan.status = RetirementPlanStatus.DRAFT
                plan.save(update_fields=["status", "updated_at"])
                gate.status = GateStatus.OPEN
                gate.save(update_fields=["status", "updated_at"])
            elif self.final_decision == GateResult.DEFERRED:
                plan.status = RetirementPlanStatus.PASSED
                plan.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="retirement.final_decision.record",
                    resource_type="stage_gate",
                    resource_public_id=gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "final_decision": record.final_decision,
                        "plan_status": plan.status,
                    },
                )
            )
            return RetirementDecisionResult(decision=record, plan=plan)
