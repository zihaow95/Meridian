"""Authorization engine fixtures."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.authorization.context import (
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.assignment import (
    RoleAssignment,
    ScopeType,
    build_scope_key,
)
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus


@pytest.fixture
def platform_admin_role(db: None) -> Role:
    role, _ = Role.objects.get_or_create(
        role_code="SYSTEM_ADMIN",
        defaults={
            "name": "System Administrator",
            "role_type": RoleType.PLATFORM,
            "is_critical": True,
        },
    )
    action, _ = PermissionAction.objects.get_or_create(
        action_code="platform.settings.read",
        defaults={
            "resource_type": "platform",
            "action_category": ActionCategory.READ,
        },
    )
    RolePermission.objects.get_or_create(
        role=role,
        action=action,
        defaults={
            "max_data_level": DataSensitivityLevel.INTERNAL,
            "requires_object_scope": False,
        },
    )
    return role


@pytest.fixture
def role_assign_action(db: None) -> PermissionAction:
    action, _ = PermissionAction.objects.get_or_create(
        action_code="authorization.role.assign",
        defaults={
            "resource_type": "authorization.role",
            "action_category": ActionCategory.ADMIN,
        },
    )
    return action


@pytest.fixture
def platform_admin_user(
    organization: Organization,
    platform_admin_role: Role,
    role_assign_action: PermissionAction,
) -> User:
    admin = User.objects.create_user(
        organization=organization,
        display_name="Platform Admin",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    RolePermission.objects.get_or_create(
        role=platform_admin_role,
        action=role_assign_action,
        defaults={
            "max_data_level": DataSensitivityLevel.INTERNAL,
            "requires_object_scope": False,
        },
    )
    role_revoke_action, _ = PermissionAction.objects.get_or_create(
        action_code="authorization.role.revoke",
        defaults={
            "resource_type": "authorization.role",
            "action_category": ActionCategory.ADMIN,
        },
    )
    RolePermission.objects.get_or_create(
        role=platform_admin_role,
        action=role_revoke_action,
        defaults={
            "max_data_level": DataSensitivityLevel.INTERNAL,
            "requires_object_scope": False,
        },
    )
    provision_action, _ = PermissionAction.objects.get_or_create(
        action_code="system_actor.retirement.provision",
        defaults={
            "resource_type": "system_actor",
            "action_category": ActionCategory.ADMIN,
        },
    )
    RolePermission.objects.get_or_create(
        role=platform_admin_role,
        action=provision_action,
        defaults={
            "max_data_level": DataSensitivityLevel.INTERNAL,
            "requires_object_scope": False,
        },
    )
    scope_id = admin.organization_id
    RoleAssignment.objects.get_or_create(
        user=admin,
        role=platform_admin_role,
        scope_type=ScopeType.ORGANIZATION,
        scope_key=build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=scope_id),
        defaults={
            "scope_id": scope_id,
            "effective_from": timezone.now(),
            "configured_by": admin,
            "status": "ACTIVE",
            "active_slot": 1,
        },
    )
    return admin


@pytest.fixture
def platform_admin_subject(platform_admin_user: User) -> AuthorizationSubject:
    return AuthorizationSubject(
        user=platform_admin_user,
        role_codes=frozenset({"SYSTEM_ADMIN"}),
    )


@pytest.fixture
def highly_sensitive_resource(organization: Organization) -> ResourceDescriptor:
    return ResourceDescriptor(
        resource_type="product.formula",
        public_id=uuid4(),
        organization_id=organization.id,
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
    )


@pytest.fixture
def product_read_action(db: None) -> PermissionAction:
    action, _ = PermissionAction.objects.get_or_create(
        action_code="product.formula.read",
        defaults={
            "resource_type": "product.formula",
            "action_category": ActionCategory.READ,
        },
    )
    return action
