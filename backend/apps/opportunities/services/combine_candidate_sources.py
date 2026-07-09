"""Merge additional case-approved opportunities into an existing candidate."""

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
from apps.opportunities.errors import CandidateSourceNotCaseApproved
from apps.opportunities.models import (
    CandidateSource,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
    SourceRole,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class CombineCandidateSources:
    context: CommandContext
    candidate_public_id: UUID
    opportunity_public_ids: list[UUID]

    def execute(self) -> ProjectCandidate:
        actor = self.context.actor
        now = self.context.occurred_at

        if not self.opportunity_public_ids:
            raise ValidationFailedError(message="At least one opportunity is required.")

        with transaction.atomic():
            candidate = (
                ProjectCandidate.objects.select_for_update()
                .filter(
                    public_id=self.candidate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if candidate is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="candidate.combine",
                resource=ResourceDescriptor(
                    resource_type="project_candidate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            for opp_public_id in self.opportunity_public_ids:
                opportunity = Opportunity.objects.filter(
                    public_id=opp_public_id,
                    organization_id=actor.organization_id,
                ).first()
                if opportunity is None:
                    raise PermissionDeniedError()
                if opportunity.proposal_status != ProposalStatus.CASE_APPROVED:
                    raise CandidateSourceNotCaseApproved()

                CandidateSource.objects.get_or_create(
                    candidate=candidate,
                    opportunity=opportunity,
                    defaults={
                        "organization": candidate.organization,
                        "source_role": SourceRole.ADDITIONAL,
                        "is_active": True,
                        "linked_at": now,
                        "linked_by": actor,
                    },
                )

            candidate.version_no += 1
            candidate.save(update_fields=["version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="candidate.combine",
                    resource_type="project_candidate",
                    resource_public_id=candidate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "added_sources": [str(pid) for pid in self.opportunity_public_ids],
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="candidate.sources_combined",
                    aggregate_type="project_candidate",
                    aggregate_id=candidate.public_id,
                    payload={"candidate_public_id": str(candidate.public_id)},
                    occurred_at=now,
                )
            )

        return candidate
