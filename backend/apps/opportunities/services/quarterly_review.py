"""Apply a quarterly review outcome to a deferred item (append-only)."""

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
from apps.opportunities.errors import (
    DeferRecordNotActive,
    QuarterlyActionInvalid,
)
from apps.opportunities.models import (
    CandidateStatus,
    DeferRecord,
    DeferReviewEntry,
    DeferStatus,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    QuarterlyAction,
)
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.models import (
    GateMaterialReference,
    GateStatus,
    MaterialType,
    StageGateInstance,
    SubjectType,
)

_SUBJECT_OPPORTUNITY = "OPPORTUNITY"


@dataclass
class QuarterlyReview:
    context: CommandContext
    defer_record_public_id: UUID
    action: str
    note: str = ""
    new_restart_trigger: str = ""
    new_next_review_quarter: str = ""

    def execute(self) -> DeferReviewEntry:
        actor = self.context.actor
        now = self.context.occurred_at

        if self.action not in QuarterlyAction.values:
            raise QuarterlyActionInvalid()

        with transaction.atomic():
            record = (
                DeferRecord.objects.select_for_update()
                .filter(
                    public_id=self.defer_record_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if record is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="deferred_item.review",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=record.subject_public_id,
                    organization_id=record.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if record.status != DeferStatus.ACTIVE:
                raise DeferRecordNotActive()

            resulting_cycle = self._apply_action(record, now)

            entry = DeferReviewEntry.objects.create(
                organization=record.organization,
                defer_record=record,
                action=self.action,
                note=self.note,
                new_restart_trigger=self.new_restart_trigger,
                new_next_review_quarter=self.new_next_review_quarter,
                resulting_cycle=resulting_cycle,
                reviewed_by=actor,
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="deferred_item.review",
                    resource_type="opportunity",
                    resource_public_id=record.subject_public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"action": self.action, "status": record.status},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="deferred_item.reviewed",
                    aggregate_type="opportunity",
                    aggregate_id=record.subject_public_id,
                    payload={
                        "defer_record_public_id": str(record.public_id),
                        "action": self.action,
                    },
                    occurred_at=now,
                )
            )

        return entry

    def _apply_action(self, record: DeferRecord, now: datetime) -> StageGateInstance | None:
        if self.action == QuarterlyAction.CONTINUE_DEFERRED:
            return None
        if self.action == QuarterlyAction.UPDATE_TRIGGER:
            return None
        if self.action == QuarterlyAction.CONVERT_TO_PASS:
            self._set_subject_status(record, passed=True)
            record.status = DeferStatus.CLOSED
            record.save(update_fields=["status"])
            return None
        # RESTART_REVIEW
        cycle = self._restart_review(record, now)
        record.status = DeferStatus.CLOSED
        record.save(update_fields=["status"])
        return cycle

    def _set_subject_status(self, record: DeferRecord, *, passed: bool) -> None:
        if record.subject_type == _SUBJECT_OPPORTUNITY:
            opportunity = self._locked_opportunity(record)
            opportunity.proposal_status = (
                ProposalStatus.PASSED if passed else ProposalStatus.IN_REVIEW
            )
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])
            return
        candidate = self._locked_candidate(record)
        candidate.status = CandidateStatus.PASSED if passed else CandidateStatus.ASSESSING
        candidate.version_no += 1
        candidate.save(update_fields=["status", "version_no", "updated_at"])

    def _restart_review(self, record: DeferRecord, now: datetime) -> StageGateInstance | None:
        if record.subject_type != _SUBJECT_OPPORTUNITY:
            candidate = self._locked_candidate(record)
            candidate.status = CandidateStatus.ASSESSING
            candidate.version_no += 1
            candidate.save(update_fields=["status", "version_no", "updated_at"])
            return None

        opportunity = self._locked_opportunity(record)
        version = opportunity.current_version
        material_public_id = version.public_id if version is not None else opportunity.public_id
        cycle_number = (
            StageGateInstance.objects.filter(
                subject_type=SubjectType.OPPORTUNITY,
                subject_public_id=opportunity.public_id,
                stage_code=record.stage_code,
            ).count()
            + 1
        )
        cycle = StageGateInstance.objects.create(
            organization=opportunity.organization,
            subject_type=SubjectType.OPPORTUNITY,
            subject_public_id=opportunity.public_id,
            stage_code=record.stage_code,
            cycle_number=cycle_number,
            status=GateStatus.OPEN,
            primary_material_type=MaterialType.PROPOSAL_VERSION,
            primary_material_public_id=material_public_id,
        )
        GateMaterialReference.objects.create(
            organization=opportunity.organization,
            stage_gate=cycle,
            material_type=MaterialType.PROPOSAL_VERSION,
            material_public_id=material_public_id,
            locked_at=now,
        )
        opportunity.proposal_status = ProposalStatus.IN_REVIEW
        opportunity.version_no += 1
        opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])
        return cycle

    def _locked_opportunity(self, record: DeferRecord) -> Opportunity:
        opportunity = (
            Opportunity.objects.select_for_update()
            .select_related("current_version")
            .filter(
                public_id=record.subject_public_id,
                organization_id=record.organization_id,
            )
            .first()
        )
        if opportunity is None:
            raise PermissionDeniedError()
        return opportunity

    def _locked_candidate(self, record: DeferRecord) -> ProjectCandidate:
        candidate = (
            ProjectCandidate.objects.select_for_update()
            .filter(
                public_id=record.subject_public_id,
                organization_id=record.organization_id,
            )
            .first()
        )
        if candidate is None:
            raise PermissionDeniedError()
        return candidate
