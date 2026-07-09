"""Record a defer decision and place the subject into the deferred pool."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.opportunities.errors import DeferInputMissing
from apps.opportunities.models import (
    CandidateStatus,
    DeferRecord,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
)
from apps.opportunities.services.defer_records import create_defer_record
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event

_SUBJECT_OPPORTUNITY = "OPPORTUNITY"
_SUBJECT_CANDIDATE = "PROJECT_CANDIDATE"


@dataclass
class DeferSubject:
    context: CommandContext
    subject_type: str
    subject_public_id: UUID
    stage_code: str
    defer_reason: str = ""
    restart_trigger: str = ""
    next_review_quarter: str = ""
    responsible_public_id: UUID | None = None

    def execute(self) -> DeferRecord:
        actor = self.context.actor
        now = self.context.occurred_at

        if not self.defer_reason.strip() and not self.restart_trigger.strip():
            raise DeferInputMissing()
        if self.subject_type not in {_SUBJECT_OPPORTUNITY, _SUBJECT_CANDIDATE}:
            raise ValidationFailedError(message="Unknown subject type.")

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="major_gate.final_decision.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=self.subject_public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            responsible = None
            if self.responsible_public_id is not None:
                responsible = User.objects.filter(
                    public_id=self.responsible_public_id,
                    organization_id=actor.organization_id,
                ).first()
                if responsible is None:
                    raise PermissionDeniedError()

            self._set_subject_deferred(actor.organization_id)

            record = create_defer_record(
                organization=actor.organization,
                subject_type=self.subject_type,
                subject_public_id=self.subject_public_id,
                stage_code=self.stage_code,
                defer_reason=self.defer_reason,
                restart_trigger=self.restart_trigger,
                next_review_quarter=self.next_review_quarter,
                responsible_user=responsible,
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="major_gate.final_decision.record",
                    resource_type="opportunity",
                    resource_public_id=self.subject_public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"deferred": True, "stage_code": self.stage_code},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="subject.deferred",
                    aggregate_type=self.subject_type.lower(),
                    aggregate_id=self.subject_public_id,
                    payload={"subject_public_id": str(self.subject_public_id)},
                    occurred_at=now,
                )
            )

        return record

    def _set_subject_deferred(self, organization_id: int) -> None:
        if self.subject_type == _SUBJECT_OPPORTUNITY:
            opportunity = (
                Opportunity.objects.select_for_update()
                .filter(public_id=self.subject_public_id, organization_id=organization_id)
                .first()
            )
            if opportunity is None:
                raise PermissionDeniedError()
            opportunity.proposal_status = ProposalStatus.DEFERRED
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])
            return

        candidate = (
            ProjectCandidate.objects.select_for_update()
            .filter(public_id=self.subject_public_id, organization_id=organization_id)
            .first()
        )
        if candidate is None:
            raise PermissionDeniedError()
        candidate.status = CandidateStatus.DEFERRED
        candidate.version_no += 1
        candidate.save(update_fields=["status", "version_no", "updated_at"])
