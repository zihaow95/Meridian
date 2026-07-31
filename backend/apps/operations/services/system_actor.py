"""Resolve a preconfigured system actor for scheduled retirement execution.

Provisioning is intentional and audited via management command / controlled
authorization services. Runtime task code must never create users, reactivate
disabled principals, or self-heal role grants.
"""

from __future__ import annotations

from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import Role, RolePermission, RoleStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext

SYSTEM_EMPLOYEE_NO = "SYSTEM-OPS-EXECUTOR"
SYSTEM_ROLE_CODE = "SYSTEM_RETIREMENT_EXECUTOR"
_EXECUTE_ACTION = "retirement_plan.execute"


def resolve_retirement_system_actor(organization: Organization) -> User:
    """Return the existing ACTIVE system executor for an organization.

    Raises if the principal, role assignment, or execute grant is missing or
    inactive. Does not create or repair authorization state.
    """

    user = User.objects.filter(
        organization=organization,
        employee_no=SYSTEM_EMPLOYEE_NO,
        status=UserStatus.ACTIVE,
    ).first()
    if user is None:
        raise ValidationFailedError(
            message=(
                "Retirement system executor is not provisioned for this organization. "
                "Run provision_retirement_system_actor before scheduling due execution."
            )
        )

    role = Role.objects.filter(role_code=SYSTEM_ROLE_CODE, status=RoleStatus.ACTIVE).first()
    if role is None:
        raise ValidationFailedError(message="Retirement system executor role is not active.")

    assignment = (
        RoleAssignment.objects.filter(
            user=user,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            status=AssignmentStatus.ACTIVE,
        )
        .filter(effective_to__isnull=True)
        .first()
    )
    if assignment is None:
        raise PermissionDeniedError()

    if not RolePermission.objects.filter(role=role, action__action_code=_EXECUTE_ACTION).exists():
        raise PermissionDeniedError()

    return user


def retirement_system_command_context(organization: Organization) -> CommandContext:
    return CommandContext.for_actor(resolve_retirement_system_actor(organization))
