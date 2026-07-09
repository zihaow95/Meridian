"""Split one opportunity into multiple independent project candidates."""

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
from apps.opportunities.errors import CandidateSplitInvalid
from apps.opportunities.models import Opportunity, ProjectCandidate, ProposalStatus
from apps.opportunities.services.create_project_candidate import build_candidate_from_opportunity
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class SplitProjectCandidate:
    context: CommandContext
    opportunity_public_id: UUID
    candidate_names: list[str]

    def execute(self) -> list[ProjectCandidate]:
        actor = self.context.actor
        now = self.context.occurred_at

        if not self.candidate_names:
            raise CandidateSplitInvalid()

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="candidate.split",
                resource=ResourceDescriptor(
                    resource_type="project_candidate",
                    public_id=self.opportunity_public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

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
            if opportunity.proposal_status != ProposalStatus.CASE_APPROVED:
                raise CandidateSplitInvalid()

            created: list[ProjectCandidate] = []
            for name in self.candidate_names:
                candidate = build_candidate_from_opportunity(
                    opportunity=opportunity,
                    actor=actor,
                    now=now,
                    name=name.strip(),
                )
                created.append(candidate)

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="candidate.split",
                    resource_type="opportunity",
                    resource_public_id=opportunity.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "split_count": len(created),
                        "candidate_ids": [str(c.public_id) for c in created],
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="candidate.split",
                    aggregate_type="opportunity",
                    aggregate_id=opportunity.public_id,
                    payload={"split_count": len(created)},
                    occurred_at=now,
                )
            )

        return created
