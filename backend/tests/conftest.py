"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

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
from apps.identity.models.user import User


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
def active_user(organization: Organization, db: None):
    from django.utils import timezone

    from apps.identity.models.user import User, UserStatus

    return User.objects.create_user(
        organization=organization,
        display_name="Active User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


@pytest.fixture
def another_active_user(organization: Organization, db: None):
    from django.utils import timezone

    from apps.identity.models.user import User, UserStatus

    return User.objects.create_user(
        organization=organization,
        display_name="Another Active User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
