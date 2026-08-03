"""Employee-number password login for non-production pilot access.

All three login paths (DingTalk, dev login_key, pilot password) must end in
`establish_session`. This module only decides whether a password claim is
allowed; it never invents a second session mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.identity.models.organization import Organization, OrganizationStatus
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import AuthenticationFailedError, UserNotActiveError


@dataclass(frozen=True)
class PilotLoginResult:
    user: User


@dataclass(frozen=True)
class AuthenticatePilotUser:
    organization_public_id: UUID
    employee_no: str
    password: str
    trace_id: str = ""

    def execute(self) -> PilotLoginResult:
        employee_no = self.employee_no.strip()
        organization = Organization.objects.filter(public_id=self.organization_public_id).first()
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            raise AuthenticationFailedError(message="Invalid login credentials.")

        user = User.objects.filter(organization=organization, employee_no=employee_no).first()
        if user is None:
            raise AuthenticationFailedError(message="Invalid login credentials.")

        if user.status != UserStatus.ACTIVE:
            self._audit(user, result=AuditResult.FAILURE, reason="USER_NOT_ACTIVE")
            raise UserNotActiveError()

        if not user.has_usable_password() or not user.check_password(self.password):
            self._audit(user, result=AuditResult.FAILURE, reason="INVALID_CREDENTIALS")
            raise AuthenticationFailedError(message="Invalid login credentials.")

        if not self._has_active_role(user):
            self._audit(user, result=AuditResult.FAILURE, reason="NO_ACTIVE_ROLE")
            raise AuthenticationFailedError(message="Invalid login credentials.")

        self._audit(user, result=AuditResult.SUCCESS, reason="AUTHENTICATED")
        return PilotLoginResult(user=user)

    def _has_active_role(self, user: User) -> bool:
        now = timezone.now()
        return (
            RoleAssignment.objects.filter(
                user=user,
                status=AssignmentStatus.ACTIVE,
                effective_from__lte=now,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
            .exists()
        )

    def _audit(self, user: User, *, result: str, reason: str) -> None:
        # Summaries name the employee number and outcome only. Passwords, hashes
        # and cookies must never appear here.
        summary: dict[str, Any] = {
            "employee_no": user.employee_no,
            "organization_public_id": str(user.organization.public_id),
            "outcome": reason,
        }
        append_event(
            AuditRecord(
                actor=user,
                action_code="identity.pilot_login",
                resource_type="identity.user",
                resource_public_id=user.public_id,
                result=result,
                trace_id=self.trace_id or "pilot-login",
                occurred_at=timezone.now(),
                after_summary=summary,
                reason=reason,
            )
        )
