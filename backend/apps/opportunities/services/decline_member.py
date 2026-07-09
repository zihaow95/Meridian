"""Decline a pending proposal team invitation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.opportunities.errors import OpportunityMemberInvitationInvalid
from apps.opportunities.models import InvitationStatus, Opportunity, OpportunityMember
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class DeclineOpportunityMember:
    context: CommandContext
    opportunity_public_id: UUID

    def execute(self) -> OpportunityMember:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            opportunity = (
                Opportunity.objects.select_for_update()
                .filter(
                    public_id=self.opportunity_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if opportunity is None:
                raise PermissionDeniedError()

            member = (
                OpportunityMember.objects.select_for_update()
                .filter(
                    opportunity=opportunity,
                    user=actor,
                    invitation_status=InvitationStatus.INVITED,
                    active_to__isnull=True,
                )
                .first()
            )
            if member is None:
                raise OpportunityMemberInvitationInvalid()

            member.invitation_status = InvitationStatus.DECLINED
            member.active_to = now
            member.active_membership_key = None
            member.save(
                update_fields=[
                    "invitation_status",
                    "active_to",
                    "active_membership_key",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="opportunity.member.decline",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"member_public_id": str(member.public_id)},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="opportunity.member_declined",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={
                        "opportunity_public_id": str(opportunity.public_id),
                        "member_public_id": str(member.public_id),
                    },
                    occurred_at=now,
                )
            )

        return member
