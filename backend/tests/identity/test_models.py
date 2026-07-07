"""Organization and identity binding invariants."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.identity.models.binding import BindingStatus, IdentityBinding, IdentityProvider
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus


@pytest.mark.django_db
def test_organization_public_id_is_unique(organization: Organization) -> None:
    duplicate = Organization(name="Duplicate")
    duplicate.public_id = organization.public_id
    with pytest.raises(IntegrityError):
        duplicate.save()


@pytest.mark.django_db
def test_same_dingtalk_identity_cannot_bind_two_users(
    organization: Organization,
    active_user: User,
    another_active_user: User,
) -> None:
    IdentityBinding.objects.create(
        user=active_user,
        provider=IdentityProvider.DINGTALK,
        provider_tenant_id="corp-1",
        provider_user_id="user-1",
    )
    with pytest.raises(IntegrityError):
        IdentityBinding.objects.create(
            user=another_active_user,
            provider=IdentityProvider.DINGTALK,
            provider_tenant_id="corp-1",
            provider_user_id="user-1",
        )


@pytest.mark.django_db
def test_user_belongs_to_single_organization(organization: Organization, active_user: User) -> None:
    assert active_user.organization_id == organization.id


@pytest.mark.django_db
def test_identity_binding_keeps_history_when_user_disabled(
    disabled_user: User,
    dingtalk_binding: IdentityBinding,
) -> None:
    assert disabled_user.status == UserStatus.DISABLED
    binding = IdentityBinding.objects.get(pk=dingtalk_binding.pk)
    assert binding.status == BindingStatus.ACTIVE
