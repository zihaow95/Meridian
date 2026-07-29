"""Repair helper for RoleAssignment unique index after collision tests."""

from __future__ import annotations

from django.db import connection


def repair_role_assignment_unique_constraint() -> None:
    """Restore the MySQL-safe unique index if a collision test dropped it.

    Avoid unconditional ALTER MODIFY: MySQL DDL commits implicitly and can
    break pytest-django TestCase isolation on the shared meridian_test DB.
    """

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT IS_NULLABLE FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'authorization_role_assignment'
              AND column_name = 'scope_id'
            """
        )
        row = cursor.fetchone()
        if row and row[0] == "YES":
            cursor.execute(
                """
                UPDATE authorization_role_assignment
                SET scope_id = COALESCE(scope_id, 0),
                    scope_key = CASE
                      WHEN scope_key IS NULL OR scope_key = ''
                        THEN CONCAT(scope_type, ':', COALESCE(scope_id, 0))
                      ELSE scope_key
                    END
                WHERE scope_id IS NULL OR scope_key IS NULL OR scope_key = ''
                """
            )
            cursor.execute(
                """
                UPDATE authorization_role_assignment a
                JOIN (
                  SELECT user_id, role_id, scope_type, scope_key, MIN(id) AS keep_id
                  FROM authorization_role_assignment
                  WHERE active_slot = 1
                  GROUP BY user_id, role_id, scope_type, scope_key
                  HAVING COUNT(*) > 1
                ) d ON a.user_id = d.user_id
                   AND a.role_id = d.role_id
                   AND a.scope_type = d.scope_type
                   AND a.scope_key = d.scope_key
                   AND a.active_slot = 1
                   AND a.id <> d.keep_id
                SET a.active_slot = NULL, a.status = 'INACTIVE'
                """
            )
            cursor.execute(
                """
                ALTER TABLE authorization_role_assignment
                MODIFY scope_id BIGINT NOT NULL,
                MODIFY scope_key VARCHAR(64) NOT NULL
                """
            )

        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'authorization_role_assignment'
              AND index_name = 'authorization_role_assignment_scope_key_slot_uniq'
            """
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                UPDATE authorization_role_assignment a
                JOIN (
                  SELECT user_id, role_id, scope_type, scope_key, MIN(id) AS keep_id
                  FROM authorization_role_assignment
                  WHERE active_slot = 1
                  GROUP BY user_id, role_id, scope_type, scope_key
                  HAVING COUNT(*) > 1
                ) d ON a.user_id = d.user_id
                   AND a.role_id = d.role_id
                   AND a.scope_type = d.scope_type
                   AND a.scope_key = d.scope_key
                   AND a.active_slot = 1
                   AND a.id <> d.keep_id
                SET a.active_slot = NULL, a.status = 'INACTIVE'
                """
            )
            cursor.execute(
                """
                ALTER TABLE authorization_role_assignment
                ADD CONSTRAINT authorization_role_assignment_scope_key_slot_uniq
                UNIQUE (user_id, role_id, scope_type, scope_key, active_slot)
                """
            )
