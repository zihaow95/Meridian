"""Submit a proposal for review with eligibility and content validation."""

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
    ProposalAlreadyInReview,
    ProposalRequiredContentMissing,
    ProposalSubmitterNotEligible,
    ProposalVersionConflict,
)
from apps.opportunities.models import (
    InvitationStatus,
    Opportunity,
    OpportunityMember,
    ProposalStatus,
    ProposalVersionStatus,
    QuotaCountStatus,
    QuotaLedger,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event

_SUBMITTABLE = {ProposalStatus.DRAFT, ProposalStatus.NEEDS_INFO}
_ALREADY_SUBMITTED = {ProposalStatus.SUBMITTED, ProposalStatus.IN_REVIEW}


def current_quarter(moment: datetime) -> str:
    return f"{moment.year}Q{(moment.month - 1) // 3 + 1}"


@dataclass
class SubmitProposal:
    context: CommandContext
    opportunity_public_id: UUID
    version_no: int
    idempotency_key: str

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
                action="opportunity.submit",
                resource=ResourceDescriptor(
                    resource_type="opportunity",
                    public_id=opportunity.public_id,
                    organization_id=opportunity.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed or opportunity.proposal_owner_id != actor.id:
                raise ProposalSubmitterNotEligible()

            if opportunity.proposal_status in _ALREADY_SUBMITTED:
                return opportunity
            if opportunity.proposal_status not in _SUBMITTABLE:
                raise ProposalAlreadyInReview()

            if opportunity.version_no != self.version_no:
                raise ProposalVersionConflict()

            self._validate_content(opportunity)
            self._validate_members(opportunity)

            version = opportunity.current_version
            opportunity.proposal_status = ProposalStatus.SUBMITTED
            opportunity.version_no += 1
            opportunity.save(update_fields=["proposal_status", "version_no", "updated_at"])

            if version is not None:
                version.version_status = ProposalVersionStatus.SUBMITTED
                version.submitted_at = now
                version.save(update_fields=["version_status", "submitted_at", "updated_at"])

            QuotaLedger.objects.get_or_create(
                opportunity=opportunity,
                defaults={
                    "organization": opportunity.organization,
                    "quarter": current_quarter(now),
                    "owner_type": opportunity.quota_owner_type,
                    "owner_id": opportunity.quota_owner_id,
                    "count_status": QuotaCountStatus.COUNTED,
                },
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="opportunity.submit",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    before_summary={"proposal_status": ProposalStatus.DRAFT},
                    after_summary={"proposal_status": opportunity.proposal_status},
                    request_metadata={"idempotency_key": self.idempotency_key},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="proposal.submitted",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={
                        "opportunity_public_id": str(opportunity.public_id),
                        "version_number": (version.version_number if version is not None else None),
                    },
                    occurred_at=now,
                )
            )

        return opportunity

    def _validate_content(self, opportunity: Opportunity) -> None:
        version = opportunity.current_version
        missing: list[str] = []
        if version is None:
            missing = [
                "market_analysis",
                "core_selling_points",
                "target_users_needs",
                "suggested_retail_price",
            ]
        else:
            if not version.market_analysis.strip():
                missing.append("market_analysis")
            if not version.core_selling_points.strip():
                missing.append("core_selling_points")
            if not version.target_users_needs.strip():
                missing.append("target_users_needs")
            if version.suggested_retail_price is None:
                missing.append("suggested_retail_price")
        if not opportunity.public_summary.strip():
            missing.append("public_summary")
        if missing:
            raise ProposalRequiredContentMissing(details={"missing": missing})

    def _validate_members(self, opportunity: Opportunity) -> None:
        from apps.identity.models.user import UserStatus

        has_inactive = (
            OpportunityMember.objects.filter(
                opportunity=opportunity,
                invitation_status=InvitationStatus.ACCEPTED,
                active_to__isnull=True,
            )
            .exclude(user__status=UserStatus.ACTIVE)
            .exists()
        )
        if has_inactive:
            raise ValidationFailedError(message="A proposal member is no longer an active user.")
