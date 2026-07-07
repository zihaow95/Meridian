"""Role assignment command with in-transaction re-authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone

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

    def execute(self) -> RoleAssignment:
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
            return RoleAssignment.objects.create(
                user=self.target,
                role=self.role,
                scope_type=self.scope_type,
                scope_id=self.scope_id,
                effective_from=self.effective_from or timezone.now(),
                configured_by=self.actor,
                approval_reference=self.approval_reference,
            )


def _subject_for(user: User) -> AuthorizationSubject:
    from apps.authorization.context import AuthorizationSubject
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
