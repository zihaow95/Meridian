"""Authorization administration API rules."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.authorization.models.assignment import RoleAssignment
from apps.authorization.models.role import Role, RoleType


@pytest.mark.django_db
def test_role_catalog_requires_read_permission(client: Client, active_user) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/authorization/roles")
    assert response.status_code == 404


@pytest.mark.django_db
def test_role_reader_can_list_roles(
    client: Client, active_user, grant_action, platform_admin_role
) -> None:
    grant_action(active_user, "authorization.role.read", "authorization.role")
    client.force_login(active_user)
    response = client.get("/api/v1/authorization/roles")
    assert response.status_code == 200
    role_codes = [row["role_code"] for row in response.json()]
    assert platform_admin_role.role_code in role_codes


@pytest.mark.django_db
def test_role_assigner_can_create_assignment(
    client: Client,
    platform_admin_user,
    active_user,
    grant_action,
    role_assign_action,
) -> None:
    grant_action(platform_admin_user, "authorization.role.assign", "authorization.role")
    target_role = Role.objects.create(
        role_code="VIEWER",
        name="Viewer",
        role_type=RoleType.BUSINESS,
    )
    client.force_login(platform_admin_user)
    response = client.post(
        f"/api/v1/authorization/users/{active_user.public_id}/assignments",
        data={"role_code": target_role.role_code, "approval_reference": "AP-100"},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert RoleAssignment.objects.filter(user=active_user, role=target_role).exists()
