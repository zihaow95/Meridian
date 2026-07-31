"""Create an ITERATION opportunity draft owned by a designated eligible owner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.opportunities.errors import ProposalOwnerNotEligible
from apps.opportunities.member_keys import active_membership_key
from apps.opportunities.models import (
    InitialType,
    InvitationStatus,
    MemberRole,
    Opportunity,
    OpportunityMember,
    ProposalStatus,
    ProposalVersion,
    ProposalVersionStatus,
    QuotaOwnerType,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext


@dataclass
class CreateIterationOpportunityDraftFromSource:
    """Owned by opportunities; creates DRAFT ITERATION opportunity for a verified owner."""

    context: CommandContext
    proposal_owner_public_id: uuid.UUID
    title: str
    public_summary: str = ""
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    market_analysis: str = ""
    core_selling_points: str = ""
    target_users_needs: str = ""

    def execute(self) -> Opportunity:
        actor = self.context.actor
        now = self.context.occurred_at
        title = (self.title or "").strip()
        if not title:
            raise ValidationFailedError(message="title is required.")

        with transaction.atomic():
            owner = User.objects.filter(
                organization_id=actor.organization_id,
                public_id=self.proposal_owner_public_id,
            ).first()
            if owner is None or owner.status != UserStatus.ACTIVE:
                raise ProposalOwnerNotEligible()

            owner_decision = authorize(
                subject_for(owner),
                action="opportunity.create",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=None,
                    organization_id=owner.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not owner_decision.allowed:
                raise ProposalOwnerNotEligible()

            content_snapshot = dict(self.source_snapshot or {})
            opportunity = Opportunity.objects.create(
                organization=actor.organization,
                business_no=f"OPP-{uuid.uuid4().hex[:8].upper()}",
                title=title,
                public_summary=self.public_summary,
                initial_type=InitialType.ITERATION,
                proposal_owner=owner,
                owner_department_id=None,
                quota_owner_type=QuotaOwnerType.USER,
                quota_owner_id=owner.id,
                proposal_status=ProposalStatus.DRAFT,
                version_no=1,
            )
            version = ProposalVersion.objects.create(
                organization=actor.organization,
                opportunity=opportunity,
                version_number=1,
                version_status=ProposalVersionStatus.DRAFT,
                market_analysis=self.market_analysis,
                core_selling_points=self.core_selling_points,
                target_users_needs=self.target_users_needs,
                suggested_retail_price=None,
                content_snapshot=content_snapshot,
            )
            opportunity.current_version = version
            opportunity.save(update_fields=["current_version", "updated_at"])

            OpportunityMember.objects.create(
                organization=actor.organization,
                opportunity=opportunity,
                user=owner,
                member_role=MemberRole.OWNER,
                invitation_status=InvitationStatus.ACCEPTED,
                active_from=now,
                active_membership_key=active_membership_key(
                    opportunity.id,
                    owner.id,
                    MemberRole.OWNER,
                ),
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="opportunity.create",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "proposal_status": opportunity.proposal_status,
                        "initial_type": opportunity.initial_type,
                        "proposal_owner_public_id": str(owner.public_id),
                        "source": "operating_issue_iteration",
                    },
                )
            )
            return opportunity
