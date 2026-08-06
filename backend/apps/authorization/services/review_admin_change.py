"""Review pending administrative change requests."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationDecision,
    ResourceDescriptor,
)
from apps.authorization.models.admin_change import AdminChangeRequest, AdminChangeStatus
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext


class ReviewerMustDiffer(Exception):
    pass


class AdminChangeNotPending(Exception):
    pass


class AdminChangeReviewDenied(Exception):
    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


@dataclass(frozen=True)
class ReviewAdminChange:
    actor: User
    request: AdminChangeRequest
    context: CommandContext | None = None
    # Domains reuse this state machine under their own action so that reviewing
    # one kind of change does not grant generic administrative review authority.
    action_code: str = "authorization.admin_change.review"
    resource_type: str = "authorization.admin_change_request"

    def approve(self) -> AdminChangeRequest:
        return self._review(decision=AdminChangeStatus.APPROVED)

    def reject(self) -> AdminChangeRequest:
        return self._review(decision=AdminChangeStatus.REJECTED)

    def _review(self, *, decision: str) -> AdminChangeRequest:
        command_context = self.context or CommandContext.for_actor(self.actor)
        with transaction.atomic():
            request = AdminChangeRequest.objects.select_for_update().get(pk=self.request.pk)
            if request.proposed_by_id == self.actor.pk:
                raise ReviewerMustDiffer()
            if request.status != AdminChangeStatus.PENDING:
                raise AdminChangeNotPending()
            if request.expires_at <= timezone.now():
                request.status = AdminChangeStatus.EXPIRED
                request.save(update_fields=["status", "updated_at"])
                raise AdminChangeNotPending()

            auth_decision = authorize(
                subject_for(self.actor),
                action=self.action_code,
                resource=ResourceDescriptor(
                    resource_type=self.resource_type,
                    public_id=request.public_id,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise AdminChangeReviewDenied(auth_decision)

            request.status = decision
            request.reviewed_by = self.actor
            request.reviewed_at = command_context.occurred_at
            request.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code=self.action_code,
                    resource_type=self.resource_type,
                    resource_public_id=request.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={"status": request.status},
                )
            )
            return request
