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
from apps.identity.models.user import User
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
            action_code="authorization.role.revoke",
            resource_public_id=first.public_id,
            result=AuditResult.SUCCESS,
            reason="deactivate",
        ).count()
        == 1
    )
    revoke_audit = AuditEvent.objects.get(
        action_code="authorization.role.revoke",
        resource_public_id=first.public_id,
        result=AuditResult.SUCCESS,
    )
    assert revoke_audit.before_summary["status"] == AssignmentStatus.ACTIVE
    assert revoke_audit.after_summary["status"] == AssignmentStatus.INACTIVE

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
def test_deactivated_role_is_denied_on_next_authorization_request(
    platform_admin_user,
    active_user,
    role_assign_action,
) -> None:
    from apps.authorization.context import AuthorizationContext, ResourceDescriptor
    from apps.authorization.services.subject import subject_for

    target_role = Role.objects.create(
        role_code="VIEWER_IMMEDIATE_REVOKE",
        name="Viewer Immediate Revoke",
        role_type=RoleType.BUSINESS,
    )
    RolePermission.objects.create(
        role=target_role,
        action=role_assign_action,
        max_data_level="INTERNAL",
        requires_object_scope=False,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        approval_reference="AP-IMMEDIATE-REVOKE",
    ).execute()
    resource = ResourceDescriptor(
        resource_type="authorization.role",
        public_id=target_role.public_id,
        organization_id=active_user.organization_id,
    )

    assert auth_engine.authorize(
        subject_for(active_user),
        action="authorization.role.assign",
        resource=resource,
        context=AuthorizationContext.current(),
    ).allowed

    DeactivateRoleAssignment(
        actor=platform_admin_user,
        assignment_public_id=assignment.public_id,
        context=CommandContext.for_actor(platform_admin_user),
    ).execute()

    decision = auth_engine.authorize(
        subject_for(active_user),
        action="authorization.role.assign",
        resource=resource,
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is False
    assert decision.reason_code == "NO_ALLOWING_POLICY"


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


@pytest.mark.django_db(transaction=True)
def test_assign_denied_when_actor_disabled_before_lock(
    platform_admin_user,
    active_user,
) -> None:
    """Disable commits on a separate connection before Assign takes locks."""

    from apps.identity.models.user import UserStatus

    target_role = Role.objects.create(
        role_code="VIEWER_STALE_ACTOR",
        name="Viewer Stale Actor",
        role_type=RoleType.BUSINESS,
    )
    assert platform_admin_user.status == UserStatus.ACTIVE

    disabled = threading.Event()

    def _disable_actor() -> None:
        close_old_connections()
        try:
            User.objects.filter(pk=platform_admin_user.pk).update(
                status=UserStatus.DISABLED,
                disabled_at=timezone.now(),
            )
        finally:
            disabled.set()
            connections.close_all()

    worker = threading.Thread(target=_disable_actor)
    worker.start()
    assert disabled.wait(timeout=10)
    worker.join(timeout=10)

    # In-memory actor is still ACTIVE; DB row is DISABLED.
    assert platform_admin_user.status == UserStatus.ACTIVE

    with pytest.raises(RoleAssignmentDenied) as exc_info:
        AssignRole(
            actor=platform_admin_user,
            target=active_user,
            role=target_role,
            approval_reference="AP-STALE",
        ).execute()
    assert exc_info.value.decision.reason_code == "USER_NOT_ACTIVE"
    assert RoleAssignment.objects.filter(user=active_user, role=target_role).count() == 0
    assert (
        AuditEvent.objects.filter(
            action_code="authorization.role.assign",
            result=AuditResult.SUCCESS,
        ).count()
        == 0
    )


@pytest.mark.django_db(transaction=True)
def test_deactivate_denied_when_actor_disabled_before_lock(
    platform_admin_user,
    active_user,
) -> None:
    from apps.identity.models.user import UserStatus

    target_role = Role.objects.create(
        role_code="VIEWER_STALE_REVOKE",
        name="Viewer Stale Revoke",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        approval_reference="AP-STALE-REV-1",
    ).execute()

    disabled = threading.Event()

    def _disable_actor() -> None:
        close_old_connections()
        try:
            User.objects.filter(pk=platform_admin_user.pk).update(
                status=UserStatus.DISABLED,
                disabled_at=timezone.now(),
            )
        finally:
            disabled.set()
            connections.close_all()

    worker = threading.Thread(target=_disable_actor)
    worker.start()
    assert disabled.wait(timeout=10)
    worker.join(timeout=10)
    assert platform_admin_user.status == UserStatus.ACTIVE

    with pytest.raises(RoleAssignmentDeactivateDenied) as exc_info:
        DeactivateRoleAssignment(
            actor=platform_admin_user,
            assignment_public_id=assignment.public_id,
            context=CommandContext.for_actor(platform_admin_user),
        ).execute()
    assert exc_info.value.decision.reason_code == "USER_NOT_ACTIVE"
    assignment.refresh_from_db()
    assert assignment.status == AssignmentStatus.ACTIVE
    assert assignment.active_slot == 1
    assert (
        AuditEvent.objects.filter(
            action_code="authorization.role.revoke",
            result=AuditResult.SUCCESS,
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_deactivate_denied_when_actor_has_assign_but_not_revoke(
    platform_admin_user,
    active_user,
    platform_admin_role,
) -> None:
    from apps.authorization.models.role import PermissionAction, RolePermission

    target_role = Role.objects.create(
        role_code="VIEWER_ASSIGN_ONLY",
        name="Viewer Assign Only",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        approval_reference="AP-ASSIGN-ONLY",
    ).execute()
    revoke_action = PermissionAction.objects.get(action_code="authorization.role.revoke")
    RolePermission.objects.filter(role=platform_admin_role, action=revoke_action).delete()

    with pytest.raises(RoleAssignmentDeactivateDenied):
        DeactivateRoleAssignment(
            actor=platform_admin_user,
            assignment_public_id=assignment.public_id,
            context=CommandContext.for_actor(platform_admin_user),
        ).execute()
    assignment.refresh_from_db()
    assert assignment.status == AssignmentStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_deactivate_rolls_back_when_audit_write_fails(
    platform_admin_user,
    active_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.audit.services.append_event import AuditWriteFailed

    target_role = Role.objects.create(
        role_code="VIEWER_AUDIT_FAIL",
        name="Viewer Audit Fail",
        role_type=RoleType.BUSINESS,
    )
    assignment = AssignRole(
        actor=platform_admin_user,
        target=active_user,
        role=target_role,
        approval_reference="AP-AUDIT-FAIL",
    ).execute()

    def _raise(*args: object, **kwargs: object) -> None:
        raise AuditWriteFailed("audit insert failed")

    monkeypatch.setattr(
        "apps.authorization.services.deactivate_role_assignment.append_event",
        _raise,
    )
    with pytest.raises(AuditWriteFailed):
        DeactivateRoleAssignment(
            actor=platform_admin_user,
            assignment_public_id=assignment.public_id,
            context=CommandContext.for_actor(platform_admin_user),
        ).execute()
    assignment.refresh_from_db()
    assert assignment.status == AssignmentStatus.ACTIVE
    assert assignment.active_slot == 1
