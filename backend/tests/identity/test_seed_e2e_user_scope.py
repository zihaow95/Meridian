"""seed_e2e_user must create normalized RoleAssignment scopes on a fresh org."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment, ScopeType, build_scope_key
from apps.identity.management.commands.seed_e2e_user import (
    E2E_APPROVER_LOGIN_KEY,
    E2E_LIMITED_LOGIN_KEY,
    E2E_LOGIN_KEY,
    E2E_ORG_NAME,
    Command,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.notifications.models import Todo


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

    organization = Organization.objects.get(name=E2E_ORG_NAME)
    user = User.objects.get(login_key=E2E_LOGIN_KEY)
    first_assignments = list(
        RoleAssignment.objects.filter(user=user)
        .order_by("id")
        .values_list(
            "id",
            "public_id",
            "role_id",
            "scope_type",
            "scope_id",
            "scope_key",
            "status",
            "active_slot",
        )
    )
    first_todo = Todo.objects.get(assignee=user, dedup_key="e2e:todo")
    first_activated_at = dict(
        User.objects.filter(
            login_key__in=(
                E2E_LOGIN_KEY,
                E2E_APPROVER_LOGIN_KEY,
                E2E_LIMITED_LOGIN_KEY,
            )
        ).values_list("login_key", "activated_at")
    )

    call_command("seed_e2e_user")

    second_assignments = list(
        RoleAssignment.objects.filter(user=user)
        .order_by("id")
        .values_list(
            "id",
            "public_id",
            "role_id",
            "scope_type",
            "scope_id",
            "scope_key",
            "status",
            "active_slot",
        )
    )
    second_todo = Todo.objects.get(assignee=user, dedup_key="e2e:todo")
    second_activated_at = dict(
        User.objects.filter(
            login_key__in=(
                E2E_LOGIN_KEY,
                E2E_APPROVER_LOGIN_KEY,
                E2E_LIMITED_LOGIN_KEY,
            )
        ).values_list("login_key", "activated_at")
    )

    assert user.organization_id == organization.id
    assert second_activated_at == first_activated_at
    assert second_assignments == first_assignments
    assert all(
        scope_key == build_scope_key(scope_type=scope_type, scope_id=scope_id)
        for _, _, _, scope_type, scope_id, scope_key, _, _ in second_assignments
    )
    assert second_todo.id == first_todo.id
    assert second_todo.public_id == first_todo.public_id
    assert second_todo.source_id == first_todo.source_id == user.public_id
