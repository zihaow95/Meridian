"""Open a PROPOSAL_TO_CASE review cycle bound to a locked proposal version."""

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
from apps.opportunities.models import Opportunity, ProposalStatus
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.errors import ReviewCycleNotStartable
from apps.stage_gates.models import (
    GateMaterialReference,
    GateStatus,
    MaterialType,
    StageCode,
    StageGateInstance,
    SubjectType,
)


@dataclass
class CreateProposalReviewCycle:
    context: CommandContext
    opportunity_public_id: UUID

    def execute(self) -> StageGateInstance:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            opportunity = (
                Opportunity.objects.select_for_update()
                .select_related("current_version")
                .filter(
                    public_id=self.opportunity_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if opportunity is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="major_gate.management_conclusion.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=opportunity.public_id,
                    organization_id=opportunity.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if opportunity.proposal_status != ProposalStatus.SUBMITTED:
                raise ReviewCycleNotStartable()

            version = opportunity.current_version
            if version is None:
                raise ValidationFailedError(message="Opportunity has no submitted version.")

            active_exists = StageGateInstance.objects.filter(
                primary_material_type=MaterialType.PROPOSAL_VERSION,
                primary_material_public_id=version.public_id,
                status=GateStatus.OPEN,
            ).exists()
            if active_exists:
                raise ReviewCycleNotStartable()

            version.lock_for_review(now=now)

            cycle_number = (
                StageGateInstance.objects.filter(
                    subject_type=SubjectType.OPPORTUNITY,
                    subject_public_id=opportunity.public_id,
                    stage_code=StageCode.PROPOSAL_TO_CASE,
                ).count()
                + 1
            )
            stage_gate = StageGateInstance.objects.create(
                organization=opportunity.organization,
                subject_type=SubjectType.OPPORTUNITY,
                subject_public_id=opportunity.public_id,
                stage_code=StageCode.PROPOSAL_TO_CASE,
                cycle_number=cycle_number,
                status=GateStatus.OPEN,
                primary_material_type=MaterialType.PROPOSAL_VERSION,
                primary_material_public_id=version.public_id,
            )
            GateMaterialReference.objects.create(
                organization=opportunity.organization,
                stage_gate=stage_gate,
                material_type=MaterialType.PROPOSAL_VERSION,
                material_public_id=version.public_id,
                locked_at=now,
            )

            opportunity.proposal_status = ProposalStatus.IN_REVIEW
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="major_gate.management_conclusion.record",
                    resource_type="stage_gate",
                    resource_public_id=stage_gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "stage_code": stage_gate.stage_code,
                        "opportunity": str(opportunity.public_id),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="proposal.review_cycle_opened",
                    aggregate_type="stage_gate",
                    aggregate_id=stage_gate.public_id,
                    payload={
                        "stage_gate_public_id": str(stage_gate.public_id),
                        "opportunity_public_id": str(opportunity.public_id),
                    },
                    occurred_at=now,
                )
            )

        return stage_gate
