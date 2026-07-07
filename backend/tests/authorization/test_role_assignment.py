"""Role assignment service rules."""

from __future__ import annotations

import pytest

from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import Role, RolePermission, RoleType
from apps.authorization.services.assign_role import AssignRole, RoleAssignmentDenied


@pytest.mark.django_db
def test_critical_role_requires_approval_reference(
    platform_admin_user,
    active_user,
    role_assign_action,
) -> None:
    critical_role = Role.objects.create(
        role_code="PRODUCT_DIRECTOR",
        name="Product Director",
        role_type=RoleType.BUSINESS,
        is_critical=True,
    )
    RolePermission.objects.create(
        role=critical_role,
        action=role_assign_action,
        max_data_level="INTERNAL",
        requires_object_scope=False,
    )

    with pytest.raises(ValueError, match="approval reference"):
        AssignRole(
            actor=platform_admin_user,
            target=active_user,
            role=critical_role,
        ).execute()


@pytest.mark.django_db
def test_assign_role_denied_without_permission(active_user, organization) -> None:
    from apps.authorization.models.role import PermissionAction

    target_role = Role.objects.create(
        role_code="VIEWER",
        name="Viewer",
        role_type=RoleType.BUSINESS,
    )
    PermissionAction.objects.get_or_create(
        action_code="authorization.role.assign",
        defaults={
            "resource_type": "authorization.role",
            "action_category": "ADMIN",
        },
    )

    with pytest.raises(RoleAssignmentDenied):
        AssignRole(
            actor=active_user,
            target=active_user,
            role=target_role,
            approval_reference="AP-001",
        ).execute()


@pytest.mark.django_db
def test_assign_role_creates_assignment_when_authorized(
    platform_admin_user,
    active_user,
    platform_admin_role,
    role_assign_action,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER",
        name="Viewer",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        scope_type=ScopeType.ORGANIZATION,
        approval_reference="AP-002",
    ).execute()

    assert isinstance(assignment, RoleAssignment)
    assert assignment.user_id == active_user.id
    assert assignment.role_id == target_role.id
