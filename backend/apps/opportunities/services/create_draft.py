"""Create the product opportunity asset and its first draft version."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
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
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext


@dataclass
class CreateOpportunityDraft:
    context: CommandContext
    title: str
    initial_type: str = InitialType.UNDECIDED
    public_summary: str = ""
    quota_owner_type: str = QuotaOwnerType.USER
    owner_department_id: int | None = None
    market_analysis: str = ""
    core_selling_points: str = ""
    target_users_needs: str = ""
    suggested_retail_price: Decimal | None = None
    content_snapshot: dict = field(default_factory=dict)

    def execute(self) -> Opportunity:
        actor = self.context.actor
        now = self.context.occurred_at

        if self.quota_owner_type not in QuotaOwnerType.values:
            raise ValidationFailedError(message="Unknown quota owner type.")
        if self.initial_type not in InitialType.values:
            raise ValidationFailedError(message="Unknown initial type.")

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="opportunity.create",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=None,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if self.quota_owner_type == QuotaOwnerType.DEPARTMENT:
                if self.owner_department_id is None:
                    raise ValidationFailedError(
                        message="Department quota owner requires owner_department_id."
                    )
                quota_owner_id = self.owner_department_id
            else:
                quota_owner_id = actor.id

            opportunity = Opportunity.objects.create(
                organization=actor.organization,
                business_no=f"OPP-{uuid.uuid4().hex[:8].upper()}",
                title=self.title,
                public_summary=self.public_summary,
                initial_type=self.initial_type,
                proposal_owner=actor,
                owner_department_id=self.owner_department_id,
                quota_owner_type=self.quota_owner_type,
                quota_owner_id=quota_owner_id,
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
                suggested_retail_price=self.suggested_retail_price,
                content_snapshot=self.content_snapshot,
            )
            opportunity.current_version = version
            opportunity.save(update_fields=["current_version", "updated_at"])

            OpportunityMember.objects.create(
                organization=actor.organization,
                opportunity=opportunity,
                user=actor,
                member_role=MemberRole.OWNER,
                invitation_status=InvitationStatus.ACCEPTED,
                active_from=now,
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
                    after_summary={"proposal_status": opportunity.proposal_status},
                )
            )

        return opportunity
