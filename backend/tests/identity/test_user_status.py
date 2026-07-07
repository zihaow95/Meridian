"""User status transition rules."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models.binding import BindingStatus, IdentityBinding, IdentityProvider
from apps.identity.models.user import UserStatus
from apps.identity.services.change_user_status import ChangeUserStatus


@pytest.mark.django_db
def test_disable_user_records_disabled_at(active_user) -> None:
    ChangeUserStatus(actor=active_user, target=active_user, status=UserStatus.DISABLED).execute()
    active_user.refresh_from_db()
    assert active_user.status == UserStatus.DISABLED
    assert active_user.disabled_at is not None


@pytest.mark.django_db
def test_depart_user_records_departed_at(active_user) -> None:
    ChangeUserStatus(actor=active_user, target=active_user, status=UserStatus.DEPARTED).execute()
    active_user.refresh_from_db()
    assert active_user.status == UserStatus.DEPARTED
    assert active_user.departed_at is not None


@pytest.mark.django_db
def test_activate_user_records_activated_at(active_user) -> None:
    active_user.status = UserStatus.PENDING
    active_user.save(update_fields=["status", "updated_at"])
    ChangeUserStatus(actor=active_user, target=active_user, status=UserStatus.ACTIVE).execute()
    active_user.refresh_from_db()
    assert active_user.status == UserStatus.ACTIVE
    assert active_user.activated_at is not None


@pytest.mark.django_db
def test_status_change_does_not_delete_identity_binding(active_user) -> None:
    binding = IdentityBinding.objects.create(
        user=active_user,
        provider=IdentityProvider.DINGTALK,
        provider_tenant_id="corp-2",
        provider_user_id="user-2",
        status=BindingStatus.ACTIVE,
    )
    ChangeUserStatus(
        actor=active_user,
        target=active_user,
        status=UserStatus.DISABLED,
        at=timezone.now(),
    ).execute()
    assert IdentityBinding.objects.filter(pk=binding.pk).exists()
