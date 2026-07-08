"""Invite a collaborator to an opportunity proposal team."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.opportunities.errors import ProposalMemberLimitExceeded
from apps.opportunities.models import (
    InvitationStatus,
    MemberRole,
    Opportunity,
    OpportunityMember,
)
from apps.opportunities.services.configuration import get_opportunity_rule_snapshot
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class InviteOpportunityMember:
    context: CommandContext
    opportunity_public_id: UUID
    invitee_public_id: UUID
    contribution_note: str = ""

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

            decision = authorize(
                subject_for(actor),
                action="opportunity.member.invite",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=opportunity.public_id,
                    organization_id=opportunity.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            invitee = User.objects.filter(
                public_id=self.invitee_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if invitee is None:
                raise ValidationFailedError(message="Invitee is not a valid active user.")

            snapshot = get_opportunity_rule_snapshot(actor.organization, now)
            active_members = (
                OpportunityMember.objects.filter(opportunity=opportunity)
                .filter(Q(active_to__isnull=True) | Q(active_to__gt=now))
                .exclude(invitation_status=InvitationStatus.DECLINED)
                .count()
            )
            if active_members >= snapshot.member_limit:
                raise ProposalMemberLimitExceeded()

            existing = (
                OpportunityMember.objects.filter(
                    opportunity=opportunity,
                    user=invitee,
                    active_to__isnull=True,
                )
                .exclude(invitation_status=InvitationStatus.DECLINED)
                .first()
            )
            if existing is not None:
                raise ValidationFailedError(message="User is already a proposal member.")

            member = OpportunityMember.objects.create(
                organization=actor.organization,
                opportunity=opportunity,
                user=invitee,
                member_role=MemberRole.COLLABORATOR,
                invitation_status=InvitationStatus.INVITED,
                active_from=now,
                contribution_note=self.contribution_note,
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="opportunity.member.invite",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"invitee": str(invitee.public_id)},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="opportunity.member_invited",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={
                        "opportunity_public_id": str(opportunity.public_id),
                        "invitee_public_id": str(invitee.public_id),
                    },
                    occurred_at=now,
                )
            )

        return member
