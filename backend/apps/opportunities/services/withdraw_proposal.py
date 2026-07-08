"""Withdraw a submitted proposal back to draft before review starts."""

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
from apps.opportunities.errors import ProposalNotWithdrawable, ProposalVersionConflict
from apps.opportunities.models import (
    Opportunity,
    ProposalStatus,
    ProposalVersionStatus,
    QuotaCountStatus,
    QuotaLedger,
)
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class WithdrawProposal:
    context: CommandContext
    opportunity_public_id: UUID
    version_no: int

    def execute(self) -> Opportunity:
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
                action="opportunity.withdraw",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=opportunity.public_id,
                    organization_id=opportunity.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if opportunity.proposal_status != ProposalStatus.SUBMITTED:
                raise ProposalNotWithdrawable()

            if opportunity.version_no != self.version_no:
                raise ProposalVersionConflict()

            opportunity.proposal_status = ProposalStatus.DRAFT
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])

            version = opportunity.current_version
            if version is not None and version.version_status == (ProposalVersionStatus.SUBMITTED):
                version.version_status = ProposalVersionStatus.DRAFT
                version.submitted_at = None
                version.save(update_fields=["version_status", "submitted_at", "updated_at"])

            QuotaLedger.objects.filter(
                opportunity=opportunity,
                count_status=QuotaCountStatus.COUNTED,
            ).update(
                count_status=QuotaCountStatus.EXCLUDED,
                exclusion_reason="withdrawn",
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="opportunity.withdraw",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    before_summary={"proposal_status": ProposalStatus.SUBMITTED},
                    after_summary={"proposal_status": opportunity.proposal_status},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="proposal.withdrawn",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={"opportunity_public_id": str(opportunity.public_id)},
                    occurred_at=now,
                )
            )

        return opportunity
