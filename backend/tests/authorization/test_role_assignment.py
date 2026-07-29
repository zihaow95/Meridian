"""Role assignment service rules."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, connection, connections
from django.utils import timezone

from apps.audit.models import AuditEvent, AuditResult
from apps.authorization.models.assignment import (
    AssignmentStatus,
    RoleAssignment,
    ScopeType,
    build_scope_key,
)
from apps.authorization.models.role import Role, RolePermission, RoleType
from apps.authorization.policies import engine as auth_engine
from apps.authorization.services.assign_role import AssignRole, RoleAssignmentDenied
from apps.authorization.services.deactivate_role_assignment import (
    DeactivateRoleAssignment,
    RoleAssignmentDeactivateDenied,
)
from apps.platform.application.command import CommandContext


@pytest.mark.django_db
def test_critical_role_requires_approval_reference(
    platform_admin_user,
    active_user,
    role_assign_action,
) -> None:
    critical_role = Role.objects.create(
        role_code="PRODUCT_DIRECTOR",
        name="Product Director",
        role_type=RoleType.BUSINESS,
        is_critical=True,
    )
    RolePermission.objects.create(
        role=critical_role,
        action=role_assign_action,
        max_data_level="INTERNAL",
        requires_object_scope=False,
    )

    with pytest.raises(ValueError, match="approval reference"):
        AssignRole(
            actor=platform_admin_user,
            target=active_user,
            role=critical_role,
        ).execute()


@pytest.mark.django_db
def test_assign_role_denied_without_permission(active_user, organization) -> None:
    from apps.authorization.models.role import PermissionAction

    target_role = Role.objects.create(
        role_code="VIEWER",
        name="Viewer",
        role_type=RoleType.BUSINESS,
    )
    PermissionAction.objects.get_or_create(
        action_code="authorization.role.assign",
        defaults={
            "resource_type": "authorization.role",
            "action_category": "ADMIN",
        },
    )

    with pytest.raises(RoleAssignmentDenied):
        AssignRole(
            actor=active_user,
            target=active_user,
            role=target_role,
            approval_reference="AP-001",
        ).execute()


@pytest.mark.django_db
def test_assign_role_creates_assignment_when_authorized(
    platform_admin_user,
    active_user,
    platform_admin_role,
    role_assign_action,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER",
        name="Viewer",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        scope_type=ScopeType.ORGANIZATION,
        approval_reference="AP-002",
    ).execute()

    assert isinstance(assignment, RoleAssignment)
    assert assignment.user_id == active_user.id
    assert assignment.role_id == target_role.id
    assert assignment.scope_id == active_user.organization_id
    assert assignment.scope_key == build_scope_key(
        scope_type=ScopeType.ORGANIZATION, scope_id=active_user.organization_id
    )
    assert assignment.active_slot == 1


@pytest.mark.django_db
def test_assign_role_reauthorizes_inside_transaction(
    platform_admin_user,
    active_user,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER_TX_AUTH",
        name="Viewer Tx Auth",
        role_type=RoleType.BUSINESS,
    )
    seen_atomic = []

    real_authorize = auth_engine.authorize

    def _authorize(*args, **kwargs):
        seen_atomic.append(connection.in_atomic_block)
        return real_authorize(*args, **kwargs)

    with patch.object(auth_engine, "authorize", side_effect=_authorize):
        # Patch the symbol used by AssignRole module.
        with patch(
            "apps.authorization.services.assign_role.authorize",
            side_effect=_authorize,
        ):
            AssignRole(
                actor=platform_admin_user,
                target=active_user,
                role=target_role,
                approval_reference="AP-TX",
            ).execute()

    assert seen_atomic
    assert all(seen_atomic)


@pytest.mark.django_db
def test_org_scope_null_scope_id_normalizes_and_blocks_duplicate_active(
    platform_admin_user,
    active_user,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER_DUP",
        name="Viewer Dup",
        role_type=RoleType.BUSINESS,
    )
    first = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=None,
        approval_reference="AP-NULL-1",
    ).execute()
    assert first.scope_id == active_user.organization_id

    with pytest.raises(IntegrityError):
        AssignRole(
            actor=platform_admin_user,
            target=active_user,
            role=target_role,
            scope_type=ScopeType.ORGANIZATION,
            scope_id=None,
            approval_reference="AP-NULL-2",
        ).execute()

    assert (
        RoleAssignment.objects.filter(
            user=active_user,
            role=target_role,
            status=AssignmentStatus.ACTIVE,
            active_slot=1,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_org_assign_keeps_single_active_slot(
    platform_admin_user,
    active_user,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER_CONCURRENT",
        name="Viewer Concurrent",
        role_type=RoleType.BUSINESS,
    )
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def _run() -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            AssignRole(
                actor=platform_admin_user,
                target=active_user,
                role=target_role,
                scope_type=ScopeType.ORGANIZATION,
                scope_id=None,
                approval_reference="AP-CONCURRENT",
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

    assert len(results) == 2
    assert results.count("ok") == 1
    assert any(item.startswith("err:") for item in results)
    assert (
        RoleAssignment.objects.filter(
            user=active_user,
            role=target_role,
            status=AssignmentStatus.ACTIVE,
            active_slot=1,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_deactivate_service_clears_active_slot_audits_and_allows_reassign(
    platform_admin_user,
    active_user,
) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER_REASSIGN",
        name="Viewer Reassign",
        role_type=RoleType.BUSINESS,
    )
    first = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        scope_type=ScopeType.ORGANIZATION,
        approval_reference="AP-RE-1",
    ).execute()
    deactivated = DeactivateRoleAssignment(
        actor=platform_admin_user,
        assignment_public_id=first.public_id,
        context=CommandContext.for_actor(platform_admin_user),
        at=timezone.now(),
    ).execute()
    assert deactivated.status == AssignmentStatus.INACTIVE
    assert deactivated.active_slot is None
    assert (
        AuditEvent.objects.filter(
            action_code="authorization.role.assign",
            resource_public_id=first.public_id,
            result=AuditResult.SUCCESS,
            reason="deactivate",
        ).count()
        == 1
    )

    second = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        scope_type=ScopeType.ORGANIZATION,
        approval_reference="AP-RE-2",
    ).execute()
    assert second.id != first.id
    assert second.status == AssignmentStatus.ACTIVE
    assert second.active_slot == 1


@pytest.mark.django_db
def test_deactivate_denied_without_permission(active_user, platform_admin_user) -> None:
    target_role = Role.objects.create(
        role_code="VIEWER_DENY_DEACT",
        name="Viewer Deny Deact",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        approval_reference="AP-DENY",
    ).execute()
    with pytest.raises(RoleAssignmentDeactivateDenied):
        DeactivateRoleAssignment(
            actor=active_user,
            assignment_public_id=assignment.public_id,
            context=CommandContext.for_actor(active_user),
        ).execute()
