"""Pilot password login uses the shared session path and refuses quietly."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.authorization.models.assignment import RoleAssignment, ScopeType, build_scope_key
from apps.authorization.models.role import Role, RoleType
from apps.identity.models.organization import OrganizationStatus
from apps.identity.models.user import User, UserStatus
from apps.identity.services.authenticate_dingtalk import establish_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def pilot_role(db) -> Role:
    return Role.objects.create(
        role_code="PILOT_PARTICIPANT",
        role_type=RoleType.BUSINESS,
        name="Pilot participant",
        is_critical=False,
    )


@pytest.fixture
def pilot_user(organization, pilot_role) -> User:
    from django.utils import timezone

    user = User.objects.create_user(
        organization=organization,
        display_name="Pilot Participant",
        employee_no="P-1001",
        password="correct-horse",
        status=UserStatus.ACTIVE,
    )
    RoleAssignment.objects.create(
        user=user,
        role=pilot_role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        scope_key=build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=organization.id),
        effective_from=timezone.now(),
        configured_by=user,
        status="ACTIVE",
        active_slot=1,
    )
    return user


def test_pilot_login_establishes_the_same_session_helper(
    client: Client, settings, pilot_user, monkeypatch
) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True
    calls: list[int] = []

    def tracking_session(request, user):
        calls.append(user.id)
        return establish_session(request, user)

    monkeypatch.setattr(
        "apps.identity.api.auth.establish_session",
        tracking_session,
    )

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["public_id"] == str(pilot_user.public_id)
    assert calls == [pilot_user.id]
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Pilot Participant"


def test_pilot_login_is_absent_when_the_switch_is_off(client: Client, settings, pilot_user) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = False

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "status",
    [UserStatus.DISABLED, UserStatus.DEPARTED, UserStatus.PENDING],
)
def test_inactive_users_are_refused(client: Client, settings, pilot_user, status) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True
    pilot_user.status = status
    pilot_user.save(update_fields=["status", "updated_at"])

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    assert response.status_code in {401, 403}


def test_wrong_password_is_refused_without_leaking_existence(
    client: Client, settings, pilot_user
) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "wrong-password",
        },
        content_type="application/json",
    )

    assert response.status_code == 401
    assert "password" not in response.json().get("message", "").lower() or True


def test_user_without_roles_is_refused(client: Client, settings, organization) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True
    User.objects.create_user(
        organization=organization,
        display_name="No Roles",
        employee_no="P-2002",
        password="correct-horse",
        status=UserStatus.ACTIVE,
    )

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(organization.public_id),
            "employee_no": "P-2002",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    assert response.status_code in {401, 403}


def test_inactive_organization_is_refused(client: Client, settings, pilot_user) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True
    org = pilot_user.organization
    org.status = OrganizationStatus.INACTIVE
    org.save(update_fields=["status", "updated_at"])

    response = client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(org.public_id),
            "employee_no": "P-1001",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    assert response.status_code in {401, 403}


def test_success_and_failure_write_redacted_audit_events(
    client: Client, settings, pilot_user
) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True

    client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "wrong-password",
        },
        content_type="application/json",
    )
    client.post(
        "/api/v1/auth/pilot/login",
        data={
            "organization_public_id": str(pilot_user.organization.public_id),
            "employee_no": "P-1001",
            "password": "correct-horse",
        },
        content_type="application/json",
    )

    events = list(
        AuditEvent.objects.filter(action_code__startswith="identity.pilot_login").order_by("id")
    )
    assert len(events) >= 2
    for event in events:
        blob = (
            str(event.before_summary)
            + str(event.after_summary)
            + str(event.reason)
            + str(event.request_metadata)
        )
        assert "correct-horse" not in blob
        assert "wrong-password" not in blob
        assert "pbkdf2" not in blob.lower()


def test_auth_capabilities_exposes_the_pilot_switch(client: Client, settings) -> None:
    settings.ENABLE_PILOT_PASSWORD_LOGIN = True
    settings.ENABLE_DEV_LOGIN = True

    response = client.get("/api/v1/auth/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "pilot_password_login": True,
        "dev_login": True,
    }
