"""MigrationExecutor upgrade coverage for RoleAssignment scope_key."""

from __future__ import annotations

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_0011_migration_executor_upgrades_null_and_explicit_org_scope_collision() -> None:
    executor = MigrationExecutor(connection)
    app_0010 = ("authorization", "0010_role_assignment_active_slot")
    app_0011 = ("authorization", "0011_role_assignment_scope_key")
    # Keep later authorization migrations (e.g. 0012) restored after the probe.
    auth_leaf = [node for node in executor.loader.graph.leaf_nodes() if node[0] == "authorization"]

    try:
        executor.migrate([app_0010])
        state = executor.loader.project_state([app_0010])
        apps = state.apps
        Organization = apps.get_model("identity", "Organization")
        User = apps.get_model("identity", "User")
        Role = apps.get_model("authorization", "Role")
        RoleAssignment = apps.get_model("authorization", "RoleAssignment")

        org = Organization.objects.create(name="Scope Collision Org")
        user = User(
            organization_id=org.id,
            display_name="Collision User",
            status="ACTIVE",
            employee_no=f"EMP-{uuid.uuid4().hex[:12]}",
            login_key=f"mig-{uuid.uuid4().hex[:20]}",
            public_id=uuid.uuid4(),
            password="!",
        )
        user.save()
        role = Role.objects.create(
            role_code=f"MIG_COLLISION_{uuid.uuid4().hex[:8]}",
            name="Collision Role",
            role_type="BUSINESS",
            status="ACTIVE",
            public_id=uuid.uuid4(),
        )
        now = timezone.now()
        RoleAssignment.objects.create(
            user_id=user.id,
            role_id=role.id,
            scope_type="ORGANIZATION",
            scope_id=None,
            effective_from=now,
            configured_by_id=user.id,
            status="ACTIVE",
            active_slot=1,
            public_id=uuid.uuid4(),
        )
        RoleAssignment.objects.create(
            user_id=user.id,
            role_id=role.id,
            scope_type="ORGANIZATION",
            scope_id=org.id,
            effective_from=now,
            configured_by_id=user.id,
            status="ACTIVE",
            active_slot=1,
            public_id=uuid.uuid4(),
        )

        executor.loader.build_graph()
        executor.migrate([app_0011])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT IS_NULLABLE FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'authorization_role_assignment'
                  AND column_name = 'scope_id'
                """
            )
            assert cursor.fetchone()[0] == "NO"
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = 'authorization_role_assignment'
                  AND index_name = 'authorization_role_assignment_scope_key_slot_uniq'
                """
            )
            assert cursor.fetchone()[0] >= 1

        from apps.authorization.models.assignment import RoleAssignment as CurrentRA

        active = CurrentRA.objects.filter(
            user_id=user.id,
            role_id=role.id,
            status="ACTIVE",
            active_slot=1,
        )
        assert active.count() == 1
        assert active.get().scope_key == f"ORGANIZATION:{org.id}"
        assert active.get().scope_id == org.id

        inactive = CurrentRA.objects.filter(
            user_id=user.id,
            role_id=role.id,
            status="INACTIVE",
        )
        assert inactive.count() == 1
        assert inactive.get().active_slot is None
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(auth_leaf or [app_0011])
