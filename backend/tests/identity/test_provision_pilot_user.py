"""provision_pilot_user creates one explicit account and refuses critical roles."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditEvent
from apps.authorization.models.role import Role, RoleType
from apps.identity.models.user import User, UserStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(active_user):
    return active_user


@pytest.fixture
def participant_role(db) -> Role:
    return Role.objects.create(
        role_code="PILOT_PARTICIPANT",
        role_type=RoleType.BUSINESS,
        name="Pilot participant",
        is_critical=False,
    )


@pytest.fixture
def critical_role(db) -> Role:
    return Role.objects.create(
        role_code="BOSS",
        role_type=RoleType.BUSINESS,
        name="Boss",
        is_critical=True,
    )


def test_provision_creates_an_active_user_with_password_and_role(
    organization, operator, participant_role
) -> None:
    call_command(
        "provision_pilot_user",
        organization_public_id=str(organization.public_id),
        employee_no="P-3001",
        display_name="Pilot Three",
        password="pilot-secret",
        roles="PILOT_PARTICIPANT",
        configured_by_login_key=operator.login_key,
    )

    user = User.objects.get(organization=organization, employee_no="P-3001")
    assert user.status == UserStatus.ACTIVE
    assert user.check_password("pilot-secret")
    assert user.role_assignments.filter(role=participant_role, active_slot=1).exists()

    event = AuditEvent.objects.get(action_code="identity.pilot_account.provision")
    assert event.resource_public_id == user.public_id
    assert "password" not in str(event.after_summary).lower()
    assert "pilot-secret" not in str(event.after_summary)


def test_provision_refuses_critical_roles(
    organization, operator, participant_role, critical_role
) -> None:
    with pytest.raises(CommandError, match="Critical roles"):
        call_command(
            "provision_pilot_user",
            organization_public_id=str(organization.public_id),
            employee_no="P-3002",
            display_name="Should Fail",
            password="pilot-secret",
            roles="PILOT_PARTICIPANT,BOSS",
            configured_by_login_key=operator.login_key,
        )

    assert User.objects.filter(employee_no="P-3002").exists() is False
