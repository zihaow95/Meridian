"""Collision upgrade coverage for RoleAssignment scope_key backfill.

Uses a short ALTER + backfill + restore cycle. Always restores the unique index
in finally (and authorization conftest also repairs after every test) so a
failure cannot poison the shared meridian_test schema.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment
from apps.authorization.models.role import Role, RoleType
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from tests.authorization.role_assignment_schema import (
    repair_role_assignment_unique_constraint,
)


def _load_backfill():
    path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "authorization"
        / "migrations"
        / "0011_role_assignment_scope_key.py"
    )
    spec = importlib.util.spec_from_file_location("auth_migration_0011", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.backfill_scope_key


@pytest.mark.django_db(transaction=True)
def test_0011_backfill_dedupes_null_and_explicit_org_scope_collision() -> None:
    backfill_scope_key = _load_backfill()
    org = Organization.objects.create(name="Scope Collision Org")
    user = User.objects.create_user(
        organization=org,
        display_name="Collision User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        employee_no=f"EMP-{uuid.uuid4().hex[:12]}",
    )
    role = Role.objects.create(
        role_code=f"MIG_COLLISION_{uuid.uuid4().hex[:8]}",
        name="Collision Role",
        role_type=RoleType.BUSINESS,
    )
    now = timezone.now()
    keep = RoleAssignment.objects.create(
        user=user,
        role=role,
        scope_type="ORGANIZATION",
        scope_id=org.id,
        scope_key=f"ORGANIZATION:{org.id}",
        effective_from=now,
        configured_by=user,
        status="ACTIVE",
        active_slot=1,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE authorization_role_assignment
                DROP INDEX authorization_role_assignment_scope_key_slot_uniq
                """
            )
            cursor.execute(
                """
                ALTER TABLE authorization_role_assignment
                MODIFY scope_id BIGINT NULL,
                MODIFY scope_key VARCHAR(64) NOT NULL DEFAULT ''
                """
            )
            cursor.execute(
                """
                INSERT INTO authorization_role_assignment
                  (public_id, user_id, role_id, scope_type, scope_id, scope_key,
                   effective_from, effective_to, configured_by_id, approval_reference,
                   status, active_slot, created_at, updated_at)
                VALUES
                  (%s, %s, %s, 'ORGANIZATION', NULL, '',
                   %s, NULL, %s, '',
                   'ACTIVE', 1, %s, %s)
                """,
                [
                    uuid.uuid4().hex,
                    user.id,
                    role.id,
                    now,
                    user.id,
                    now,
                    now,
                ],
            )

        backfill_scope_key(django_apps, None)

        active = RoleAssignment.objects.filter(
            user=user, role=role, status="ACTIVE", active_slot=1
        )
        assert active.count() == 1
        assert active.get().id == keep.id
        assert active.get().scope_key == f"ORGANIZATION:{org.id}"

        inactive = RoleAssignment.objects.filter(user=user, role=role, status="INACTIVE")
        assert inactive.count() == 1
        assert inactive.get().active_slot is None
    finally:
        repair_role_assignment_unique_constraint()
