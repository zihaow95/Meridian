"""Shared fixtures for identity domain tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.models.binding import AuthState, BindingStatus, IdentityBinding, IdentityProvider
from apps.identity.models.user import User, UserStatus
from apps.integrations.dingtalk.contracts import DingTalkIdentity
from apps.integrations.dingtalk.fake_gateway import FakeDingTalkGateway


@pytest.fixture
def another_active_user(organization, db: None) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Another Active User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


@pytest.fixture
def disabled_user(organization, db: None) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Disabled User",
        status=UserStatus.DISABLED,
        disabled_at=timezone.now(),
    )


@pytest.fixture
def dingtalk_binding(disabled_user: User) -> IdentityBinding:
    return IdentityBinding.objects.create(
        user=disabled_user,
        provider=IdentityProvider.DINGTALK,
        provider_tenant_id="corp-1",
        provider_user_id="user-1",
        status=BindingStatus.ACTIVE,
    )


@pytest.fixture
def fake_dingtalk_gateway(settings: pytest.fixture) -> FakeDingTalkGateway:
    gateway = FakeDingTalkGateway()
    settings.DINGTALK_GATEWAY = gateway
    return gateway


@pytest.fixture
def valid_auth_state(db: None) -> AuthState:
    return AuthState.objects.create(
        state_hash=hashlib.sha256(b"valid").hexdigest(),
        redirect_path="/",
        expires_at=timezone.now() + timedelta(minutes=10),
    )


@pytest.fixture
def active_user_dingtalk_setup(
    active_user: User,
    fake_dingtalk_gateway: FakeDingTalkGateway,
    valid_auth_state: AuthState,
) -> User:
    IdentityBinding.objects.create(
        user=active_user,
        provider=IdentityProvider.DINGTALK,
        provider_tenant_id="corp-active",
        provider_user_id="user-active",
        status=BindingStatus.ACTIVE,
    )
    fake_dingtalk_gateway.register(
        "valid-active",
        DingTalkIdentity(tenant_id="corp-active", user_id="user-active"),
    )
    return active_user
