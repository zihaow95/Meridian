"""Appoint the case owner and, when required, a deputy leader.

The case owner must be a product manager. A deputy leader is mandatory whenever
any active source proposal was owned by a non-product-manager, and it must be an
active member of one of those source proposal teams.
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
from apps.identity.models.user import User
from apps.opportunities.errors import (
    CandidateNotAssignable,
    CandidateVersionConflict,
    CaseLeadershipRolesNotConfigured,
    CaseOwnerNotProductManager,
    DeputyLeaderInvalid,
    DeputyLeaderRequired,
)
from apps.opportunities.models import (
    CandidateSource,
    CandidateStatus,
    InvitationStatus,
    OpportunityMember,
    ProjectCandidate,
)
from apps.opportunities.services.configuration import get_opportunity_rule_snapshot
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event

_ASSIGNABLE = {CandidateStatus.AWAITING_ASSIGNMENT, CandidateStatus.ASSESSING}


@dataclass
class AssignCaseLeadership:
    context: CommandContext
    candidate_public_id: UUID
    version_no: int
    case_owner_public_id: UUID
    deputy_leader_public_id: UUID | None = None

    def execute(self) -> ProjectCandidate:
        actor = self.context.actor
        now = self.context.occurred_at

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
                action="candidate.leadership.assign",
                resource=ResourceDescriptor(
                    resource_type="project_candidate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if candidate.status not in _ASSIGNABLE:
                raise CandidateNotAssignable()
            if candidate.version_no != self.version_no:
                raise CandidateVersionConflict()

            snapshot = get_opportunity_rule_snapshot(actor.organization, now)
            if not snapshot.product_manager_roles:
                raise CaseLeadershipRolesNotConfigured()

            case_owner = self._resolve_user(self.case_owner_public_id)
            if not self._is_product_manager(case_owner, snapshot.product_manager_roles):
                raise CaseOwnerNotProductManager()

            deputy = self._resolve_deputy(candidate, snapshot.product_manager_roles)

            candidate.case_owner = case_owner
            candidate.deputy_leader = deputy
            candidate.status = CandidateStatus.ASSESSING
            candidate.version_no += 1
            candidate.save(
                update_fields=[
                    "case_owner",
                    "deputy_leader",
                    "status",
                    "version_no",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="candidate.leadership.assign",
                    resource_type="project_candidate",
                    resource_public_id=candidate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "case_owner": str(case_owner.public_id),
                        "deputy_leader": (str(deputy.public_id) if deputy else None),
                        "status": candidate.status,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="candidate.leadership_assigned",
                    aggregate_type="project_candidate",
                    aggregate_id=candidate.public_id,
                    payload={"candidate_public_id": str(candidate.public_id)},
                    occurred_at=now,
                )
            )

        return candidate

    def _resolve_user(self, public_id: UUID) -> User:
        user = User.objects.filter(
            public_id=public_id,
            organization_id=self.context.actor.organization_id,
        ).first()
        if user is None:
            raise PermissionDeniedError()
        return user

    def _is_product_manager(self, user: User, pm_roles: frozenset[str]) -> bool:
        return bool(subject_for(user).role_codes & pm_roles)

    def _resolve_deputy(self, candidate: ProjectCandidate, pm_roles: frozenset[str]) -> User | None:
        active_sources = list(
            CandidateSource.objects.filter(candidate=candidate, is_active=True).select_related(
                "opportunity", "opportunity__proposal_owner"
            )
        )
        non_pm_opportunity_ids = [
            source.opportunity_id
            for source in active_sources
            if not self._is_product_manager(source.opportunity.proposal_owner, pm_roles)
        ]
        deputy_required = bool(non_pm_opportunity_ids)

        if self.deputy_leader_public_id is None:
            if deputy_required:
                raise DeputyLeaderRequired()
            return None

        deputy = self._resolve_user(self.deputy_leader_public_id)
        eligible = OpportunityMember.objects.filter(
            opportunity_id__in=non_pm_opportunity_ids or [s.opportunity_id for s in active_sources],
            user=deputy,
            invitation_status=InvitationStatus.ACCEPTED,
            active_to__isnull=True,
        ).exists()
        if not eligible:
            raise DeputyLeaderInvalid()
        return deputy
