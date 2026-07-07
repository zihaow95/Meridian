"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.organization import Organization


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


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
