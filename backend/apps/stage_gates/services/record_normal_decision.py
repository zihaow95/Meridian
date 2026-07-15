"""Record normal (non-major) execution gate decisions."""

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
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.models import (
    ExecutionException,
    ExecutionExceptionStatus,
    ProjectStage,
    ProjectStageStatus,
    StageHandlingMode,
)
from apps.projects.services.publish_and_handover import PublishAndHandover
from apps.stage_gates.errors import GateAlreadyDecided, GateDecisionNotAllowed
from apps.stage_gates.models import (
    GateDecision,
    GateResult,
    GateStatus,
    StageGateInstance,
)


@dataclass
class RecordNormalGateDecision:
    context: CommandContext
    stage_gate_public_id: UUID
    result: str
    decision_summary: str
    idempotency_key: str
    exception_rationale: str = ""

    def execute(self) -> GateDecision:
        actor = self.context.actor
        with transaction.atomic():
            gate = (
                StageGateInstance.objects.select_for_update()
                .select_related(
                    "project",
                    "project_stage",
                    "project__product_draft",
                    "current_submission",
                )
                .filter(
                    public_id=self.stage_gate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if gate is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="normal_gate.decide",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=gate.public_id,
                    organization_id=gate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            existing = GateDecision.objects.filter(
                organization_id=gate.organization_id,
                stage_gate=gate,
                idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None:
                return existing
            if gate.status in {
                GateStatus.APPROVED,
                GateStatus.DEFERRED,
                GateStatus.PASSED,
                GateStatus.DECIDED,
            }:
                raise GateAlreadyDecided()
            if (
                gate.current_submission_id
                and GateDecision.objects.filter(submission_id=gate.current_submission_id).exists()
            ):
                raise GateAlreadyDecided()

            if self.result == GateResult.APPROVED_WITH_EXCEPTION:
                from django.db.models import Q

                from apps.authorization.models.assignment import (
                    AssignmentStatus,
                    RoleAssignment,
                )

                # Leaders may decide via object identity; exception pass needs a role grant.
                has_role_grant = (
                    RoleAssignment.objects.filter(
                        user=actor,
                        status=AssignmentStatus.ACTIVE,
                        role__permissions__action__action_code="normal_gate.decide",
                        effective_from__lte=self.context.occurred_at,
                    )
                    .filter(
                        Q(effective_to__isnull=True) | Q(effective_to__gt=self.context.occurred_at)
                    )
                    .exists()
                )
                if not has_role_grant:
                    raise GateDecisionNotAllowed()

            if gate.status != GateStatus.SUBMITTED or gate.current_submission_id is None:
                raise GateDecisionNotAllowed(message="Gate must be submitted before decision.")

            if self.result == GateResult.APPROVED_WITH_EXCEPTION and not self.exception_rationale:
                raise GateDecisionNotAllowed(message="Exception rationale is required.")

            submission = gate.current_submission
            if submission is None:
                raise GateDecisionNotAllowed(message="Gate must be submitted before decision.")

            try:
                record = GateDecision.objects.create(
                    organization=gate.organization,
                    stage_gate=gate,
                    submission=submission,
                    result=self.result,
                    decided_by=actor,
                    decision_summary=self.decision_summary,
                    exception_rationale=self.exception_rationale,
                    idempotency_key=self.idempotency_key,
                    decided_at=self.context.occurred_at,
                )
            except IntegrityError as exc:
                if GateDecision.objects.filter(submission_id=gate.current_submission_id).exists():
                    raise GateAlreadyDecided() from exc
                raise
            stage = gate.project_stage
            if self.result in {GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION}:
                gate.status = GateStatus.APPROVED
                if stage is not None:
                    stage.status = ProjectStageStatus.COMPLETED
                    stage.save(update_fields=["status", "updated_at"])
                    self._activate_next_stage(stage)
                if (
                    self.result == GateResult.APPROVED_WITH_EXCEPTION
                    and stage is not None
                    and gate.project_id is not None
                ):
                    ExecutionException.objects.create(
                        organization=gate.organization,
                        project_id=gate.project_id,
                        stage=stage,
                        exception_type=StageHandlingMode.EXEMPT,
                        previous_mode=stage.handling_mode,
                        requested_mode=StageHandlingMode.EXEMPT,
                        rationale=self.exception_rationale,
                        evidence_summary={"source": "normal_gate.approved_with_exception"},
                        requested_by=actor,
                        confirmed_by=actor,
                        status=ExecutionExceptionStatus.CONFIRMED,
                        confirmed_at=self.context.occurred_at,
                    )
            elif self.result == GateResult.NEEDS_INFO:
                gate.status = GateStatus.NEEDS_INFO
                if stage is not None and stage.status != ProjectStageStatus.ACTIVE:
                    stage.status = ProjectStageStatus.ACTIVE
                    stage.save(update_fields=["status", "updated_at"])
            elif self.result == GateResult.DEFERRED:
                gate.status = GateStatus.DEFERRED
                if stage is not None:
                    stage.status = ProjectStageStatus.DEFERRED
                    stage.save(update_fields=["status", "updated_at"])
            elif self.result == GateResult.PASSED:
                gate.status = GateStatus.PASSED
            else:
                raise GateDecisionNotAllowed(message=f"Unsupported result: {self.result}")

            gate.save(update_fields=["status", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="normal_gate.decide",
                    resource_type="stage_gate",
                    resource_public_id=gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "result": record.result,
                        "decision_public_id": str(record.public_id),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="stage_gate.decided",
                    aggregate_type="stage_gate",
                    aggregate_id=gate.public_id,
                    payload={
                        "stage_gate_public_id": str(gate.public_id),
                        "result": record.result,
                    },
                    occurred_at=self.context.occurred_at,
                )
            )
            gate_code = stage.gate_code if stage is not None else ""
            draft = gate.project.product_draft if gate.project is not None else None
            if (
                self.result in {GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION}
                and gate_code == "CHANGE_EFFECTIVE"
                and gate.project is not None
                and draft is not None
            ):
                PublishAndHandover(
                    context=self.context,
                    project_public_id=gate.project.public_id,
                    decision_public_id=record.public_id,
                    idempotency_key=f"{record.public_id}:{draft.public_id}",
                ).execute()
            return record

    def _activate_next_stage(self, stage: ProjectStage) -> None:
        nxt = (
            ProjectStage.objects.filter(
                project_id=stage.project_id,
                sequence_no__gt=stage.sequence_no,
            )
            .order_by("sequence_no")
            .first()
        )
        if nxt is None:
            return
        nxt.status = ProjectStageStatus.ACTIVE
        nxt.actual_start_at = self.context.occurred_at
        nxt.save(update_fields=["status", "actual_start_at", "updated_at"])
        project = stage.project
        project.current_stage = nxt
        project.save(update_fields=["current_stage", "updated_at"])
