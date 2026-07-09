"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

pytest_plugins = ["tests.opportunities.conftest"]

import shutil
import uuid
from pathlib import Path
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authorization.context import AuthorizationSubject, ResourceDescriptor
from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.documents.storage.filesystem import FilesystemStorage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus

_TEST_STORAGE_ROOT = Path(__file__).resolve().parent / "_storage"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def grant_action(db: None):
    """Grant a platform action to a user via role assignment."""

    def _grant(
        user: User,
        action_code: str,
        resource_type: str,
        *,
        role_code: str | None = None,
    ) -> None:
        action, _ = PermissionAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": ActionCategory.ADMIN,
            },
        )
        code = role_code or f"ROLE_{action_code.replace('.', '_').upper()}"
        role, _ = Role.objects.get_or_create(
            role_code=code,
            defaults={
                "name": code,
                "role_type": RoleType.PLATFORM,
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
        RoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "scope_type": ScopeType.ORGANIZATION,
                "effective_from": timezone.now(),
                "configured_by": user,
            },
        )

    return _grant


@pytest.fixture
def organization(db: None) -> Organization:
    return Organization.objects.create(name="Meridian Corp")


@pytest.fixture
def active_user(organization: Organization, db: None) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Active User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


@pytest.fixture
def another_active_user(organization: Organization, db: None) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Another Active User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


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


@pytest.fixture
def file_storage() -> FilesystemStorage:
    root = _TEST_STORAGE_ROOT / uuid.uuid4().hex
    storage = FilesystemStorage(root)
    yield storage
    shutil.rmtree(root, ignore_errors=True)
