"""Authorization engine fixtures."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.authorization.context import (
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.assignment import RoleAssignment, ScopeType
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
    role = Role.objects.create(
        role_code="SYSTEM_ADMIN",
        name="System Administrator",
        role_type=RoleType.PLATFORM,
        is_critical=True,
    )
    action = PermissionAction.objects.create(
        action_code="platform.settings.read",
        resource_type="platform",
        action_category=ActionCategory.READ,
    )
    RolePermission.objects.create(
        role=role,
        action=action,
        max_data_level=DataSensitivityLevel.INTERNAL,
        requires_object_scope=False,
    )
    return role


@pytest.fixture
def role_assign_action(db: None) -> PermissionAction:
    return PermissionAction.objects.create(
        action_code="authorization.role.assign",
        resource_type="authorization.role",
        action_category=ActionCategory.ADMIN,
    )


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
    RolePermission.objects.create(
        role=platform_admin_role,
        action=role_assign_action,
        max_data_level=DataSensitivityLevel.INTERNAL,
        requires_object_scope=False,
    )
    RoleAssignment.objects.create(
        user=admin,
        role=platform_admin_role,
        scope_type=ScopeType.ORGANIZATION,
        effective_from=timezone.now(),
        configured_by=admin,
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
    return PermissionAction.objects.create(
        action_code="product.formula.read",
        resource_type="product.formula",
        action_category=ActionCategory.READ,
    )
