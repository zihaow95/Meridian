"""Role assignment command with in-transaction re-authorization and audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import Role
from apps.authorization.policies.engine import authorize
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
        decision = authorize(
            _subject_for(self.actor),
            action="authorization.role.assign",
            resource=ResourceDescriptor(
                resource_type="authorization.role",
                public_id=self.role.public_id,
                organization_id=self.target.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise RoleAssignmentDenied(decision)

        if self.role.is_critical and not self.approval_reference:
            raise ValueError("Critical roles require an approval reference.")

        with transaction.atomic():
            assignment = RoleAssignment.objects.create(
                user=self.target,
                role=self.role,
                scope_type=self.scope_type,
                scope_id=self.scope_id,
                effective_from=self.effective_from or timezone.now(),
                configured_by=self.actor,
                approval_reference=self.approval_reference,
            )
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="authorization.role.assign",
                    resource_type="authorization.role_assignment",
                    resource_public_id=assignment.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={
                        "role_code": self.role.role_code,
                        "target_user_id": str(self.target.public_id),
                    },
                    reason=self.approval_reference,
                )
            )
            return assignment


def _subject_for(user: User) -> AuthorizationSubject:
    from apps.authorization.models.assignment import AssignmentStatus

    now = timezone.now()
    role_codes = frozenset(
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=now))
        .values_list("role__role_code", flat=True)
    )
    return AuthorizationSubject(user=user, role_codes=role_codes)
