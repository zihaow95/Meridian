"""Record FIRST_LAUNCH dual conclusions; approving finals hand over publication."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.models import ProjectStageStatus, ProjectStatus
from apps.projects.services.publish_and_handover import HandoverResult, PublishAndHandover
from apps.stage_gates.errors import (
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
class FirstLaunchDecisionResult:
    decision: MajorGateDecision
    handover: HandoverResult | None = None
    handover_error: str | None = None


@dataclass
class RecordFirstLaunchDecision:
    context: CommandContext
    stage_gate_public_id: UUID
    management_conclusion: str
    final_decision: str
    decision_summary: str
    idempotency_key: str
    management_conclusion_by_public_id: UUID | None = None

    def execute(self) -> FirstLaunchDecisionResult:
        actor = self.context.actor
        if (
            not self.management_conclusion
            or not self.final_decision
            or self.management_conclusion not in GateResult.values
            or self.final_decision not in GateResult.values
        ):
            raise MajorGateConclusionRequired()

        with transaction.atomic():
            gate = (
                StageGateInstance.objects.select_for_update()
                .select_related("project", "project_stage")
                .filter(
                    public_id=self.stage_gate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if gate is None:
                raise PermissionDeniedError()

            management_conclusion_by = self._authorize_and_resolve_management_actor(actor, gate)

            existing = MajorGateDecision.objects.filter(
                idempotency_key=self.idempotency_key,
                stage_gate=gate,
            ).first()
            if existing is not None:
                if existing.organization_id != gate.organization_id:
                    raise PermissionDeniedError()
                return FirstLaunchDecisionResult(decision=existing)

            if MajorGateDecision.objects.filter(stage_gate=gate).exists():
                raise MajorGateAlreadyDecided()

            project_stage = gate.project_stage
            if gate.stage_code != "FIRST_LAUNCH" and not (
                project_stage is not None and project_stage.gate_code == "FIRST_LAUNCH"
            ):
                raise GateDecisionNotAllowed(message="Gate is not a FIRST_LAUNCH decision point.")
            if gate.gate_type != GateType.MAJOR:
                raise GateDecisionNotAllowed(message="FIRST_LAUNCH requires a major gate.")

            try:
                record = MajorGateDecision.objects.create(
                    organization=gate.organization,
                    stage_gate=gate,
                    management_conclusion=self.management_conclusion,
                    management_conclusion_by=management_conclusion_by,
                    final_decision=self.final_decision,
                    final_decision_by=actor,
                    has_conclusion_difference=(self.management_conclusion != self.final_decision),
                    decision_summary=self.decision_summary,
                    idempotency_key=self.idempotency_key,
                    decided_at=self.context.occurred_at,
                )
            except IntegrityError as exc:
                existing = MajorGateDecision.objects.filter(stage_gate=gate).first()
                if existing is not None:
                    raise MajorGateAlreadyDecided() from exc
                raise

            gate.status = _GATE_STATUS_BY_RESULT.get(self.final_decision, GateStatus.DECIDED)
            close_gate_material_lock(gate)
            gate.save(update_fields=["status", "open_material_key", "updated_at"])

            stage = gate.project_stage
            project = gate.project
            if stage is not None:
                if self.final_decision == GateResult.NEEDS_INFO:
                    stage.status = ProjectStageStatus.ACTIVE
                elif self.final_decision == GateResult.DEFERRED:
                    stage.status = ProjectStageStatus.DEFERRED
                    if project is not None:
                        project.status = ProjectStatus.DEFERRED
                        project.save(update_fields=["status", "updated_at"])
                elif self.final_decision == GateResult.PASSED:
                    stage.status = ProjectStageStatus.PASSED
                    if project is not None:
                        project.status = ProjectStatus.PASSED
                        project.save(update_fields=["status", "updated_at"])
                elif self.final_decision in _APPROVING:
                    stage.status = ProjectStageStatus.COMPLETED
                stage.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="first_launch.final_decision.record",
                    resource_type="stage_gate",
                    resource_public_id=gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "management_conclusion": record.management_conclusion,
                        "final_decision": record.final_decision,
                        "decision_public_id": str(record.public_id),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="first_launch.decided",
                    aggregate_type="stage_gate",
                    aggregate_id=gate.public_id,
                    payload={
                        "stage_gate_public_id": str(gate.public_id),
                        "final_decision": record.final_decision,
                        "decision_public_id": str(record.public_id),
                    },
                    occurred_at=self.context.occurred_at,
                )
            )

            if self.final_decision not in _APPROVING or project is None:
                return FirstLaunchDecisionResult(decision=record)

            draft = project.product_draft
            if draft is None:
                raise GateDecisionNotAllowed(message="Product draft is missing for handover.")

            handover = PublishAndHandover(
                context=self.context,
                project_public_id=project.public_id,
                decision_public_id=record.public_id,
                idempotency_key=f"{record.public_id}:{draft.public_id}",
            ).execute()
            return FirstLaunchDecisionResult(
                decision=record,
                handover=handover,
                handover_error=handover.error_code,
            )

    def _authorize_and_resolve_management_actor(self, actor: User, gate: StageGateInstance) -> User:
        resource = ResourceDescriptor(
            resource_type="stage_gate",
            public_id=gate.public_id,
            organization_id=gate.organization_id,
        )
        context = AuthorizationContext.current()
        if self.management_conclusion_by_public_id is not None:
            management_user = User.objects.filter(
                public_id=self.management_conclusion_by_public_id,
                organization_id=gate.organization_id,
            ).first()
            if management_user is None:
                raise PermissionDeniedError()
            management_auth = authorize(
                subject_for(management_user),
                action="first_launch.management_conclusion.record",
                resource=resource,
                context=context,
            )
            if not management_auth.allowed:
                raise PermissionDeniedError()
            final_auth = authorize(
                subject_for(actor),
                action="first_launch.final_decision.record",
                resource=resource,
                context=context,
            )
            if not final_auth.allowed:
                raise PermissionDeniedError()
            return management_user

        for action in (
            "first_launch.management_conclusion.record",
            "first_launch.final_decision.record",
        ):
            decision = authorize(
                subject_for(actor),
                action=action,
                resource=resource,
                context=context,
            )
            if not decision.allowed:
                raise PermissionDeniedError()
        return actor
