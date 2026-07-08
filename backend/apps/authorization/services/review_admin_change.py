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

    def approve(self) -> AdminChangeRequest:
        return self._review(decision=AdminChangeStatus.APPROVED)

    def reject(self) -> AdminChangeRequest:
        return self._review(decision=AdminChangeStatus.REJECTED)

    def _review(self, *, decision: str) -> AdminChangeRequest:
        if self.request.proposed_by_id == self.actor.pk:
            raise ReviewerMustDiffer()
        if self.request.status != AdminChangeStatus.PENDING:
            raise AdminChangeNotPending()
        if self.request.expires_at <= timezone.now():
            self.request.status = AdminChangeStatus.EXPIRED
            self.request.save(update_fields=["status", "updated_at"])
            raise AdminChangeNotPending()

        command_context = self.context or CommandContext.for_actor(self.actor)
        with transaction.atomic():
            auth_decision = authorize(
                subject_for(self.actor),
                action="authorization.admin_change.review",
                resource=ResourceDescriptor(
                    resource_type="authorization.admin_change_request",
                    public_id=self.request.public_id,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise AdminChangeReviewDenied(auth_decision)

            self.request.status = decision
            self.request.reviewed_by = self.actor
            self.request.reviewed_at = command_context.occurred_at
            self.request.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="authorization.admin_change.review",
                    resource_type="authorization.admin_change_request",
                    resource_public_id=self.request.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={"status": self.request.status},
                )
            )
            return self.request
