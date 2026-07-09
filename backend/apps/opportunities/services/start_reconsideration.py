"""Start a reconsideration: append a record and open a fresh review cycle.

The original pass/defer cycle is never edited; a new StageGateInstance cycle is
created and linked back to it.
"""

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
from apps.opportunities.errors import (
    ReconsiderationNotAllowed,
    SubjectNotReconsiderable,
)
from apps.opportunities.models import (
    CandidateSource,
    CandidateStatus,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    Reconsideration,
)
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.material_keys import open_material_key
from apps.stage_gates.models import (
    GateMaterialReference,
    GateStatus,
    MaterialType,
    StageGateInstance,
    SubjectType,
)

_RECONFIRM_SOURCE_STATES = {
    CandidateStatus.AWAITING_ASSIGNMENT,
    CandidateStatus.ASSESSING,
    CandidateStatus.NEEDS_INFO,
}


@dataclass
class StartReconsideration:
    context: CommandContext
    original_subject_public_id: UUID
    target_stage_code: str
    reason: str = ""
    subject_type: str = SubjectType.OPPORTUNITY

    def execute(self) -> Reconsideration:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="reconsideration.create",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=self.original_subject_public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise ReconsiderationNotAllowed()

            opportunity = (
                Opportunity.objects.select_for_update()
                .select_related("current_version")
                .filter(
                    public_id=self.original_subject_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if opportunity is None:
                raise PermissionDeniedError()
            if opportunity.proposal_status != ProposalStatus.PASSED:
                raise SubjectNotReconsiderable()

            original_cycle = (
                StageGateInstance.objects.filter(
                    subject_type=SubjectType.OPPORTUNITY,
                    subject_public_id=opportunity.public_id,
                    status=GateStatus.DECIDED,
                )
                .order_by("-created_at")
                .first()
            )
            if original_cycle is None:
                raise SubjectNotReconsiderable()

            version = opportunity.current_version
            material_public_id = version.public_id if version is not None else opportunity.public_id

            cycle_number = (
                StageGateInstance.objects.filter(
                    subject_type=SubjectType.OPPORTUNITY,
                    subject_public_id=opportunity.public_id,
                    stage_code=self.target_stage_code,
                ).count()
                + 1
            )
            new_cycle = StageGateInstance.objects.create(
                organization=opportunity.organization,
                subject_type=SubjectType.OPPORTUNITY,
                subject_public_id=opportunity.public_id,
                stage_code=self.target_stage_code,
                cycle_number=cycle_number,
                status=GateStatus.OPEN,
                primary_material_type=MaterialType.PROPOSAL_VERSION,
                primary_material_public_id=material_public_id,
                previous_cycle=original_cycle,
                open_material_key=open_material_key(
                    MaterialType.PROPOSAL_VERSION,
                    material_public_id,
                ),
            )
            GateMaterialReference.objects.create(
                organization=opportunity.organization,
                stage_gate=new_cycle,
                material_type=MaterialType.PROPOSAL_VERSION,
                material_public_id=material_public_id,
                locked_at=now,
            )

            opportunity.proposal_status = ProposalStatus.IN_REVIEW
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])

            eligibility_basis = (
                "OWNER" if opportunity.proposal_owner_id == actor.id else "ELIGIBLE_PROPOSER"
            )
            reconsideration = Reconsideration.objects.create(
                organization=opportunity.organization,
                subject_type=SubjectType.OPPORTUNITY,
                original_subject_public_id=opportunity.public_id,
                original_cycle=original_cycle,
                new_cycle=new_cycle,
                target_stage_code=self.target_stage_code,
                reason=self.reason,
                eligibility_basis=eligibility_basis,
                initiated_by=actor,
            )

            self._flag_dependent_candidates(opportunity)

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="reconsideration.create",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "target_stage_code": self.target_stage_code,
                        "new_cycle": str(new_cycle.public_id),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="subject.reconsideration_started",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={"reconsideration_public_id": str(reconsideration.public_id)},
                    occurred_at=now,
                )
            )

        return reconsideration

    def _flag_dependent_candidates(self, opportunity: Opportunity) -> None:
        candidate_ids = CandidateSource.objects.filter(
            opportunity=opportunity, is_active=True
        ).values_list("candidate_id", flat=True)
        ProjectCandidate.objects.filter(
            id__in=list(candidate_ids),
            status__in=_RECONFIRM_SOURCE_STATES,
        ).update(status=CandidateStatus.SOURCE_RECONFIRM_REQUIRED)
