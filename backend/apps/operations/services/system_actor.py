"""Controlled system actor for scheduled operations execution."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleStatus,
    RoleType,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.application.command import CommandContext

_SYSTEM_EMPLOYEE_NO = "SYSTEM-OPS-EXECUTOR"
_SYSTEM_ROLE_CODE = "SYSTEM_RETIREMENT_EXECUTOR"
_SYSTEM_DISPLAY_NAME = "System Retirement Executor"

_EXECUTE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("retirement_plan.execute", "retirement_plan"),
)


def get_or_create_retirement_system_actor(organization: Organization) -> User:
    """Return an org-scoped system principal with retirement execute grants.

    The actor uses an unusable password and is not intended for interactive login.
    Role grants are re-asserted on each call so revoked creator permissions cannot
    block already-approved due retirement execution.
    """

    with transaction.atomic():
        user = User.objects.filter(
            organization=organization, employee_no=_SYSTEM_EMPLOYEE_NO
        ).first()
        if user is None:
            user = User.objects.create_user(
                organization=organization,
                display_name=_SYSTEM_DISPLAY_NAME,
                employee_no=_SYSTEM_EMPLOYEE_NO,
                status=UserStatus.ACTIVE,
            )
        if user.status != UserStatus.ACTIVE:
            user.status = UserStatus.ACTIVE
            user.disabled_at = None
            user.save(update_fields=["status", "disabled_at", "updated_at"])
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password", "updated_at"])

        role, _ = Role.objects.get_or_create(
            role_code=_SYSTEM_ROLE_CODE,
            defaults={
                "name": "System Retirement Executor",
                "role_type": RoleType.BUSINESS,
                "status": RoleStatus.ACTIVE,
            },
        )
        if role.status != RoleStatus.ACTIVE:
            role.status = RoleStatus.ACTIVE
            role.save(update_fields=["status", "updated_at"])

        for action_code, resource_type in _EXECUTE_ACTIONS:
            action, _ = PermissionAction.objects.get_or_create(
                action_code=action_code,
                defaults={
                    "resource_type": resource_type,
                    "action_category": ActionCategory.WRITE,
                    "description": action_code,
                },
            )
            RolePermission.objects.get_or_create(
                role=role,
                action=action,
                defaults={
                    "max_data_level": DataSensitivityLevel.HIGHLY_SENSITIVE,
                    "requires_object_scope": False,
                },
            )

        assignment = (
            RoleAssignment.objects.filter(
                user=user,
                role=role,
                scope_type=ScopeType.ORGANIZATION,
            )
            .order_by("id")
            .first()
        )
        now = timezone.now()
        if assignment is None:
            RoleAssignment.objects.create(
                user=user,
                role=role,
                scope_type=ScopeType.ORGANIZATION,
                scope_id=organization.id,
                effective_from=user.created_at or now,
                effective_to=None,
                configured_by=user,
                status=AssignmentStatus.ACTIVE,
            )
        else:
            assignment.status = AssignmentStatus.ACTIVE
            assignment.effective_to = None
            assignment.scope_id = organization.id
            assignment.save(update_fields=["status", "effective_to", "scope_id", "updated_at"])
        return user


def retirement_system_command_context(organization: Organization) -> CommandContext:
    return CommandContext.for_actor(get_or_create_retirement_system_actor(organization))
