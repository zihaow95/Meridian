"""Controlled provision of the retirement system executor must authorize and audit."""

from __future__ import annotations

import threading

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connections
from django.utils import timezone

from apps.audit.models import AuditEvent, AuditResult
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import Role, RolePermission
from apps.authorization.services.provision_retirement_system_actor import (
    ProvisionRetirementSystemActor,
    ProvisionRetirementSystemActorDenied,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.operations.services.system_actor import SYSTEM_EMPLOYEE_NO, SYSTEM_ROLE_CODE
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext


def _executor_count(organization: Organization) -> int:
    return User.objects.filter(organization=organization, employee_no=SYSTEM_EMPLOYEE_NO).count()


def _assignment_count(organization: Organization) -> int:
    return RoleAssignment.objects.filter(
        user__organization=organization,
        role__role_code=SYSTEM_ROLE_CODE,
    ).count()


@pytest.mark.django_db(transaction=True)
def test_command_requires_organization_and_actor(organization, active_user) -> None:
    with pytest.raises(CommandError):
        call_command("provision_retirement_system_actor")
    with pytest.raises(CommandError):
        call_command(
            "provision_retirement_system_actor",
            organization_id=organization.id,
        )
    with pytest.raises(CommandError):
        call_command(
            "provision_retirement_system_actor",
            actor_login_key=active_user.login_key,
        )
    assert _executor_count(organization) == 0
    assert _assignment_count(organization) == 0


@pytest.mark.django_db(transaction=True)
def test_ordinary_active_actor_is_denied_and_audited_without_state(
    organization, active_user
) -> None:
    with pytest.raises((ProvisionRetirementSystemActorDenied, PermissionDeniedError)):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(active_user),
            organization=organization,
        ).execute()

    assert _executor_count(organization) == 0
    assert _assignment_count(organization) == 0
    assert (
        AuditEvent.objects.filter(
            action_code="system_actor.retirement.provision",
            actor_user=active_user,
            result=AuditResult.FAILURE,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_cross_organization_actor_is_denied_without_state(
    organization, active_user, grant_action
) -> None:
    other_org = Organization.objects.create(name="Other Corp")
    outsider = User.objects.create_user(
        organization=other_org,
        display_name="Outsider Admin",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(outsider, "authorization.role.assign", "authorization.role")

    with pytest.raises(
        (ProvisionRetirementSystemActorDenied, PermissionDeniedError, ValidationFailedError)
    ):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(outsider),
            organization=organization,
        ).execute()

    assert _executor_count(organization) == 0
    assert _assignment_count(organization) == 0
    assert (
        AuditEvent.objects.filter(
            action_code="system_actor.retirement.provision",
            actor_user=outsider,
            result=AuditResult.FAILURE,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_authorized_admin_provisions_with_success_audit(organization, platform_admin_user) -> None:
    executor = ProvisionRetirementSystemActor(
        context=CommandContext.for_actor(platform_admin_user),
        organization=organization,
    ).execute()

    assert executor.employee_no == SYSTEM_EMPLOYEE_NO
    assert executor.organization_id == organization.id
    assert executor.status == UserStatus.ACTIVE
    assignment = RoleAssignment.objects.get(
        user=executor, role__role_code=SYSTEM_ROLE_CODE, status=AssignmentStatus.ACTIVE
    )
    assert assignment.configured_by_id == platform_admin_user.id
    assert assignment.configured_by_id != executor.id
    assert RolePermission.objects.filter(
        role__role_code=SYSTEM_ROLE_CODE,
        action__action_code="retirement_plan.execute",
    ).exists()
    assert (
        AuditEvent.objects.filter(
            action_code="system_actor.retirement.provision",
            actor_user=platform_admin_user,
            result=AuditResult.SUCCESS,
            resource_public_id=executor.public_id,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_command_delegates_to_authorized_service(organization, platform_admin_user) -> None:
    call_command(
        "provision_retirement_system_actor",
        organization_id=organization.id,
        actor_login_key=platform_admin_user.login_key,
    )
    assert _executor_count(organization) == 1
    assert (
        AuditEvent.objects.filter(
            action_code="system_actor.retirement.provision",
            result=AuditResult.SUCCESS,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_active_assignment_unique_per_user_role_scope(organization, platform_admin_user) -> None:
    executor = ProvisionRetirementSystemActor(
        context=CommandContext.for_actor(platform_admin_user),
        organization=organization,
    ).execute()
    role = Role.objects.get(role_code=SYSTEM_ROLE_CODE)
    scope_key = f"{ScopeType.ORGANIZATION}:{organization.id}"
    with pytest.raises(IntegrityError):
        RoleAssignment.objects.create(
            user=executor,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization.id,
            scope_key=scope_key,
            effective_from=timezone.now(),
            effective_to=None,
            configured_by=platform_admin_user,
            status=AssignmentStatus.ACTIVE,
            active_slot=1,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_provision_does_not_duplicate_executor(
    organization, platform_admin_user
) -> None:
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def _run() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            ProvisionRetirementSystemActor(
                context=CommandContext.for_actor(platform_admin_user),
                organization=organization,
            ).execute()
            with lock:
                results.append("ok")
        except Exception as exc:  # noqa: BLE001
            with lock:
                results.append(f"err:{type(exc).__name__}")
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_run)
    t2 = threading.Thread(target=_run)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert _executor_count(organization) == 1
    assert _assignment_count(organization) == 1
    assert results.count("ok") == 2
    assert len(results) == 2
    assert (
        AuditEvent.objects.filter(
            action_code="system_actor.retirement.provision",
            actor_user=platform_admin_user,
            result=AuditResult.SUCCESS,
        ).count()
        == 2
    )


@pytest.mark.django_db(transaction=True)
def test_disabled_executor_is_failure_audited(organization, platform_admin_user) -> None:
    User.objects.create_user(
        organization=organization,
        display_name="Disabled Executor",
        employee_no=SYSTEM_EMPLOYEE_NO,
        status=UserStatus.DISABLED,
        activated_at=timezone.now(),
    )
    with pytest.raises(ValidationFailedError):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(platform_admin_user),
            organization=organization,
        ).execute()
    failure = AuditEvent.objects.get(
        action_code="system_actor.retirement.provision",
        actor_user=platform_admin_user,
        result=AuditResult.FAILURE,
    )
    assert failure.reason == "executor_inactive"
    assert _assignment_count(organization) == 0


@pytest.mark.django_db(transaction=True)
def test_inactive_system_role_is_failure_audited(organization, platform_admin_user) -> None:
    from apps.authorization.models.role import RoleStatus, RoleType

    Role.objects.create(
        role_code=SYSTEM_ROLE_CODE,
        name="System Retirement Executor",
        role_type=RoleType.BUSINESS,
        status=RoleStatus.INACTIVE,
    )
    with pytest.raises(ValidationFailedError):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(platform_admin_user),
            organization=organization,
        ).execute()
    failure = AuditEvent.objects.get(
        action_code="system_actor.retirement.provision",
        actor_user=platform_admin_user,
        result=AuditResult.FAILURE,
    )
    assert failure.reason == "role_inactive"


@pytest.mark.django_db(transaction=True)
def test_inactive_assignment_is_failure_audited(organization, platform_admin_user) -> None:
    from apps.authorization.models.assignment import build_scope_key
    from apps.authorization.models.role import RoleStatus, RoleType

    executor = User.objects.create_user(
        organization=organization,
        display_name="System Retirement Executor",
        employee_no=SYSTEM_EMPLOYEE_NO,
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    executor.set_unusable_password()
    executor.save(update_fields=["password", "updated_at"])
    role = Role.objects.create(
        role_code=SYSTEM_ROLE_CODE,
        name="System Retirement Executor",
        role_type=RoleType.BUSINESS,
        status=RoleStatus.ACTIVE,
    )
    RoleAssignment.objects.create(
        user=executor,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        scope_key=build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=organization.id),
        effective_from=timezone.now(),
        effective_to=timezone.now(),
        configured_by=platform_admin_user,
        status=AssignmentStatus.INACTIVE,
        active_slot=None,
    )
    with pytest.raises(ValidationFailedError):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(platform_admin_user),
            organization=organization,
        ).execute()
    failure = AuditEvent.objects.get(
        action_code="system_actor.retirement.provision",
        actor_user=platform_admin_user,
        result=AuditResult.FAILURE,
    )
    assert failure.reason == "assignment_inactive"


@pytest.mark.django_db(transaction=True)
def test_provision_prefers_active_assignment_over_historical_inactive(
    organization, platform_admin_user
) -> None:
    from apps.authorization.models.assignment import build_scope_key
    from apps.authorization.models.role import RoleStatus, RoleType

    executor = User.objects.create_user(
        organization=organization,
        display_name="System Retirement Executor",
        employee_no=SYSTEM_EMPLOYEE_NO,
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    executor.set_unusable_password()
    executor.save(update_fields=["password", "updated_at"])
    role = Role.objects.create(
        role_code=SYSTEM_ROLE_CODE,
        name="System Retirement Executor",
        role_type=RoleType.BUSINESS,
        status=RoleStatus.ACTIVE,
    )
    scope_key = build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=organization.id)
    RoleAssignment.objects.create(
        user=executor,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        scope_key=scope_key,
        effective_from=timezone.now(),
        effective_to=timezone.now(),
        configured_by=platform_admin_user,
        status=AssignmentStatus.INACTIVE,
        active_slot=None,
    )
    active = RoleAssignment.objects.create(
        user=executor,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        scope_key=scope_key,
        effective_from=timezone.now(),
        effective_to=None,
        configured_by=platform_admin_user,
        status=AssignmentStatus.ACTIVE,
        active_slot=1,
    )
    result = ProvisionRetirementSystemActor(
        context=CommandContext.for_actor(platform_admin_user),
        organization=organization,
    ).execute()
    assert result.id == executor.id
    assert (
        RoleAssignment.objects.filter(
            user=executor,
            role=role,
            status=AssignmentStatus.ACTIVE,
            active_slot=1,
        )
        .get()
        .id
        == active.id
    )


@pytest.mark.django_db(transaction=True)
def test_provision_reauthorizes_inside_transaction(organization, platform_admin_user) -> None:
    from unittest.mock import patch

    from django.db import connection

    seen_atomic: list[bool] = []

    def _authorize(*args, **kwargs):
        from apps.authorization.policies.engine import authorize as real

        seen_atomic.append(connection.in_atomic_block)
        return real(*args, **kwargs)

    with patch(
        "apps.authorization.services.provision_retirement_system_actor.authorize",
        side_effect=_authorize,
    ):
        ProvisionRetirementSystemActor(
            context=CommandContext.for_actor(platform_admin_user),
            organization=organization,
        ).execute()

    assert seen_atomic
    assert all(seen_atomic)
