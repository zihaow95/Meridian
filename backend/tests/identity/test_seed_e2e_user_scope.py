"""seed_e2e_user must create normalized RoleAssignment scopes on a fresh org."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment, ScopeType, build_scope_key
from apps.identity.management.commands.seed_e2e_user import (
    E2E_LOGIN_KEY,
    E2E_ORG_NAME,
    Command,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus


@pytest.mark.django_db
def test_seed_e2e_grant_writes_scope_fields_and_is_idempotent() -> None:
    organization = Organization.objects.create(name="Fresh Seed Org")
    user = User.objects.create_user(
        organization=organization,
        display_name="Fresh Seed User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    command = Command()
    command._grant_action(user, "opportunity.create", "opportunity", role_code="PROPOSER")
    command._grant_action(user, "opportunity.create", "opportunity", role_code="PROPOSER")

    assignments = RoleAssignment.objects.filter(user=user)
    assert assignments.count() == 1
    assignment = assignments.get()
    assert assignment.scope_type == ScopeType.ORGANIZATION
    assert assignment.scope_id == organization.id
    assert assignment.scope_key == build_scope_key(
        scope_type=ScopeType.ORGANIZATION, scope_id=organization.id
    )
    assert assignment.active_slot == 1


@pytest.mark.django_db
def test_seed_e2e_user_command_runs_twice_successfully() -> None:
    call_command("seed_e2e_user")
    call_command("seed_e2e_user")

    organization = Organization.objects.get(name=E2E_ORG_NAME)
    user = User.objects.get(login_key=E2E_LOGIN_KEY)
    assert user.organization_id == organization.id
    assert (
        RoleAssignment.objects.filter(user=user)
        .exclude(scope_key="")
        .exclude(scope_id__isnull=True)
        .exists()
    )
    assert not RoleAssignment.objects.filter(user=user, scope_key="").exists()
