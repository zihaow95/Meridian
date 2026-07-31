"""Convert an operating issue into a DRAFT iteration opportunity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.errors import (
    IssueImmutableState,
    IssueVersionConflict,
    IterationProposalAlreadyCreated,
)
from apps.operations.models import (
    IssueConversion,
    IssueConversionType,
    IssueSignal,
    OperatingIssue,
    OperatingIssueStatus,
)
from apps.operations.policies.identity_provider import resolve_effective_assignments
from apps.opportunities.services.create_iteration_from_source import (
    CreateIterationOpportunityDraftFromSource,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


def _not_found() -> PermissionDeniedError:
    return PermissionDeniedError()


def _authorize_convert(*, actor: User, issue: OperatingIssue) -> None:
    decision = authorize(
        subject_for(actor),
        action="iteration_proposal.convert",
        resource=ResourceDescriptor(
            resource_type="operating_issue",
            public_id=issue.public_id,
            organization_id=actor.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={"product_public_id": str(issue.product.public_id)},
        ),
        context=AuthorizationContext.current(),
    )
    if decision.allowed:
        return
    assignments = resolve_effective_assignments(user=actor, organization_id=actor.organization_id)
    required = DataSensitivityLevel.SENSITIVE_CONTROLLED
    for assignment in assignments:
        if assignment.product_id != issue.product_id:
            continue
        if LEVEL_RANK.get(assignment.max_data_level, 0) < LEVEL_RANK.get(required, 0):
            continue
        return
    raise _not_found()


def _build_source_snapshot(issue: OperatingIssue) -> dict:
    links = list(
        IssueSignal.objects.filter(issue=issue)
        .select_related("signal", "signal__channel")
        .order_by("-is_primary", "id")
    )
    return {
        "issue_public_id": str(issue.public_id),
        "issue_business_no": issue.business_no,
        "product_public_id": str(issue.product.public_id),
        "phenomenon_summary": issue.phenomenon_summary,
        "recommendation_type": issue.recommendation_type,
        "data_snapshot_public_id": (
            str(issue.data_snapshot.public_id) if issue.data_snapshot is not None else None
        ),
        "data_snapshot_content_hash": (
            issue.data_snapshot.content_hash if issue.data_snapshot is not None else None
        ),
        "signals": [
            {
                "signal_public_id": str(link.signal.public_id),
                "scope_key": link.signal.scope_key,
                "sku_public_id": str(link.signal.scope_id),
                "channel_public_id": (
                    str(link.signal.channel.public_id) if link.signal.channel is not None else None
                ),
                "is_primary": link.is_primary,
            }
            for link in links
        ],
        "source_type": issue.source_type,
        "source_materials_json": issue.source_materials_json,
    }


@dataclass
class ConvertIssueToIterationProposal:
    context: CommandContext
    issue_public_id: UUID
    proposal_owner_public_id: UUID
    idempotency_key: str
    version_no: int | None = None

    def execute(self) -> OperatingIssue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        key = (self.idempotency_key or "").strip()
        if not key:
            raise ValidationFailedError(message="idempotency_key is required.")

        with transaction.atomic():
            existing = (
                IssueConversion.objects.select_related("issue")
                .filter(organization_id=actor.organization_id, idempotency_key=key)
                .first()
            )
            if existing is not None:
                return existing.issue

            issue = (
                OperatingIssue.objects.select_for_update()
                .select_related("product", "data_snapshot")
                .filter(organization_id=actor.organization_id, public_id=self.issue_public_id)
                .first()
            )
            if issue is None:
                raise _not_found()
            _authorize_convert(actor=actor, issue=issue)

            if self.version_no is not None and issue.version_no != self.version_no:
                raise IssueVersionConflict()

            if issue.status == OperatingIssueStatus.CONVERTED_TO_PROPOSAL:
                raise IterationProposalAlreadyCreated()
            if issue.status in {
                OperatingIssueStatus.CLOSED,
                OperatingIssueStatus.RETIREMENT_REVIEW,
            }:
                raise IssueImmutableState()
            if IssueConversion.objects.filter(
                issue=issue, conversion_type=IssueConversionType.ITERATION_PROPOSAL
            ).exists():
                raise IterationProposalAlreadyCreated()

            source_snapshot = _build_source_snapshot(issue)
            opportunity = CreateIterationOpportunityDraftFromSource(
                context=self.context,
                proposal_owner_public_id=self.proposal_owner_public_id,
                title=f"Iteration: {issue.title}",
                public_summary=issue.phenomenon_summary,
                source_snapshot=source_snapshot,
                market_analysis=issue.phenomenon_summary,
                core_selling_points=issue.recommendation_type or "",
                target_users_needs="",
            ).execute()

            try:
                IssueConversion.objects.create(
                    organization_id=actor.organization_id,
                    issue=issue,
                    conversion_type=IssueConversionType.ITERATION_PROPOSAL,
                    opportunity_public_id=opportunity.public_id,
                    source_snapshot_json=source_snapshot,
                    idempotency_key=key,
                    converted_by=actor,
                    converted_at=now,
                )
            except IntegrityError as exc:
                # Concurrent convert: return the winner's issue.
                winner = (
                    IssueConversion.objects.select_related("issue")
                    .filter(
                        issue=issue,
                        conversion_type=IssueConversionType.ITERATION_PROPOSAL,
                    )
                    .first()
                )
                if winner is not None:
                    return winner.issue
                raise ValidationFailedError(message="Conversion conflict.") from exc

            issue.linked_opportunity_id = opportunity.public_id
            issue.status = OperatingIssueStatus.CONVERTED_TO_PROPOSAL
            issue.version_no += 1
            issue.save(
                update_fields=[
                    "linked_opportunity_id",
                    "status",
                    "version_no",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="iteration_proposal.convert",
                    resource_type="operating_issue",
                    resource_public_id=issue.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={
                        "opportunity_public_id": str(opportunity.public_id),
                        "status": issue.status,
                    },
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="operating_issue.converted",
                    aggregate_type="operating_issue",
                    aggregate_id=issue.public_id,
                    payload={
                        "issue_public_id": str(issue.public_id),
                        "opportunity_public_id": str(opportunity.public_id),
                        "organization_id": issue.organization_id,
                    },
                    occurred_at=now,
                )
            )
            return issue
