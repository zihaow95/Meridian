"""Controlled deactivation of role assignments with audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

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
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.authorization.policies.engine import authorize
from apps.authorization.services.role_assignment_locks import lock_organization_and_users
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError
from apps.platform.application.command import CommandContext

_REVOKE_ACTION = "authorization.role.revoke"


class RoleAssignmentDeactivateDenied(Exception):
    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


@dataclass(frozen=True)
class DeactivateRoleAssignment:
    """Deactivate one assignment after org/user locks and in-transaction reauth."""

    actor: User
    assignment_public_id: UUID
    context: CommandContext | None = None
    at: datetime | None = None

    def execute(self) -> RoleAssignment:
        command_context = self.context or CommandContext.for_actor(self.actor)
        now = self.at or timezone.now()

        with transaction.atomic():
            assignment = (
                RoleAssignment.objects.select_related("user", "role")
                .filter(public_id=self.assignment_public_id)
                .first()
            )
            if assignment is None:
                raise ResourceNotFoundError()
            if assignment.user.organization_id != self.actor.organization_id:
                raise ResourceNotFoundError()

            _, locked_users = lock_organization_and_users(
                organization_id=assignment.user.organization_id,
                user_ids=(self.actor.id, assignment.user_id),
            )
            locked_actor = locked_users[self.actor.id]
            assignment = (
                RoleAssignment.objects.select_for_update()
                .select_related("user", "role")
                .get(pk=assignment.pk)
            )

            decision = authorize(
                subject_for(locked_actor),
                action=_REVOKE_ACTION,
                resource=ResourceDescriptor(
                    resource_type="authorization.role",
                    public_id=assignment.role.public_id,
                    organization_id=assignment.user.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise RoleAssignmentDeactivateDenied(decision)

            if assignment.status == AssignmentStatus.INACTIVE and assignment.active_slot is None:
                return assignment

            before_summary = {
                "role_code": assignment.role.role_code,
                "target_user_id": str(assignment.user.public_id),
                "scope_key": assignment.scope_key,
                "status": assignment.status,
            }
            assignment.status = AssignmentStatus.INACTIVE
            assignment.active_slot = None
            if assignment.effective_to is None:
                assignment.effective_to = now
            assignment.save(update_fields=["status", "active_slot", "effective_to", "updated_at"])
            append_event(
                AuditRecord(
                    actor=locked_actor,
                    action_code=_REVOKE_ACTION,
                    resource_type="authorization.role_assignment",
                    resource_public_id=assignment.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(locked_actor),
                    before_summary=before_summary,
                    after_summary={
                        "role_code": assignment.role.role_code,
                        "target_user_id": str(assignment.user.public_id),
                        "scope_key": assignment.scope_key,
                        "status": AssignmentStatus.INACTIVE,
                    },
                    reason="deactivate",
                )
            )
            return assignment
