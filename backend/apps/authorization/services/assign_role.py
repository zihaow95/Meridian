"""Role assignment command with in-transaction re-authorization and audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
from apps.authorization.models.assignment import (
    RoleAssignment,
    ScopeType,
    build_scope_key,
    resolve_scope_id,
)
from apps.authorization.models.role import Role
from apps.authorization.policies.engine import authorize
from apps.authorization.services.role_assignment_locks import lock_organization_and_users
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext


class RoleAssignmentDenied(Exception):
    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


@dataclass(frozen=True)
class AssignRole:
    actor: User
    target: User
    role: Role
    scope_type: str = ScopeType.ORGANIZATION
    scope_id: int | None = None
    effective_from: datetime | None = None
    approval_reference: str = ""
    context: CommandContext | None = None

    def execute(self) -> RoleAssignment:
        command_context = self.context or CommandContext.for_actor(self.actor)

        if self.role.is_critical and not self.approval_reference:
            raise ValueError("Critical roles require an approval reference.")

        resolved_scope_id = resolve_scope_id(
            scope_type=self.scope_type,
            scope_id=self.scope_id,
            organization_id=self.target.organization_id,
        )
        scope_key = build_scope_key(scope_type=self.scope_type, scope_id=resolved_scope_id)

        with transaction.atomic():
            _, locked_users = lock_organization_and_users(
                organization_id=self.target.organization_id,
                user_ids=(self.actor.id, self.target.id),
            )
            locked_actor = locked_users[self.actor.id]
            locked_target = locked_users[self.target.id]
            decision = authorize(
                subject_for(locked_actor),
                action="authorization.role.assign",
                resource=ResourceDescriptor(
                    resource_type="authorization.role",
                    public_id=self.role.public_id,
                    organization_id=locked_target.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise RoleAssignmentDenied(decision)

            assignment = RoleAssignment.objects.create(
                user=locked_target,
                role=self.role,
                scope_type=self.scope_type,
                scope_id=resolved_scope_id,
                scope_key=scope_key,
                effective_from=self.effective_from or timezone.now(),
                configured_by=locked_actor,
                approval_reference=self.approval_reference,
                status="ACTIVE",
                active_slot=1,
            )
            append_event(
                AuditRecord(
                    actor=locked_actor,
                    action_code="authorization.role.assign",
                    resource_type="authorization.role_assignment",
                    resource_public_id=assignment.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(locked_actor),
                    after_summary={
                        "role_code": self.role.role_code,
                        "target_user_id": str(locked_target.public_id),
                        "scope_key": scope_key,
                    },
                    reason=self.approval_reference,
                )
            )
            return assignment
