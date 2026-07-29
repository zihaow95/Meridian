"""Verify E2E seed first-run and repeat-run behavior on a clean MySQL database."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import MySQLdb

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
SNAPSHOT_QUERIES = {
    "users": """
        SELECT id, public_id, login_key, organization_id, status, activated_at
        FROM {database}.identity_user
        WHERE login_key IN ('e2e-active-user', 'e2e-approver-user', 'e2e-limited-user')
        ORDER BY login_key
    """,
    "role_assignments": """
        SELECT
            ra.id, ra.public_id, u.id, u.public_id, u.login_key,
            r.id, r.public_id, r.role_code, ra.scope_type, ra.scope_id,
            ra.scope_key, ra.status, ra.active_slot, ra.configured_by_id
        FROM {database}.authorization_role_assignment AS ra
        JOIN {database}.identity_user AS u ON u.id = ra.user_id
        JOIN {database}.authorization_role AS r ON r.id = ra.role_id
        WHERE u.login_key IN ('e2e-active-user', 'e2e-approver-user', 'e2e-limited-user')
        ORDER BY u.login_key, r.role_code, ra.id
    """,
    "todo": """
        SELECT
            t.id, t.public_id, u.login_key, t.todo_type, t.source_type,
            t.source_id, t.action_code, t.status, t.dedup_key, t.deep_link, t.title
        FROM {database}.notifications_todo AS t
        JOIN {database}.identity_user AS u ON u.id = t.assignee_id
        WHERE u.login_key = 'e2e-active-user' AND t.dedup_key = 'e2e:todo'
        ORDER BY t.id
    """,
    "operating_catalog": """
        SELECT
            p.id, p.public_id, p.business_no, p.lifecycle_status, p.product_owner_id,
            p.primary_version_id, v.id, v.public_id, v.version_code, v.status,
            s.id, s.public_id, s.sku_code, s.status, s.production_status,
            c.id, c.public_id, c.channel_code, c.configuration_version, c.channel_status
        FROM {database}.products_product_asset AS p
        JOIN {database}.products_product_version AS v ON v.product_id = p.id
        JOIN {database}.products_sku AS s ON s.product_version_id = v.id
        JOIN {database}.products_channel_configuration AS c ON c.sku_id = s.id
        WHERE p.business_no = 'E2E-OPS-PRD'
          AND s.sku_code = 'SKU-E2E-OPS'
          AND c.channel_code = 'TMALL'
        ORDER BY v.id, s.id, c.id
    """,
    "data_source": """
        SELECT ds.id, ds.public_id, ds.source_code, ds.status, ds.configuration_version_id
        FROM {database}.integrations_data_source AS ds
        JOIN {database}.identity_organization AS org ON org.id = ds.organization_id
        WHERE org.name = 'E2E Organization' AND ds.source_code = 'E2E_OPS_SRC'
        ORDER BY ds.id
    """,
    "metrics_and_rules": """
        SELECT 'metric', id, public_id, metric_code, version_number, status
        FROM {database}.operations_metric_definition_version
        WHERE metric_code IN ('PRODUCTION_QTY', 'GROSS_SALES')
        UNION ALL
        SELECT 'rule', id, public_id, rule_code, version_number, status
        FROM {database}.operations_risk_rule_version
        WHERE rule_code = 'E2E_QUARTER_SHELF_MIN_PROD'
        ORDER BY 1, 4, 5
    """,
    "monitoring": """
        SELECT
            ms.id, ms.public_id, ms.project_id, ms.product_version_id,
            ms.source_decision_public_id, ms.status,
            ma.id, ma.public_id, ma.supervisor_id, ma.product_id, ma.sku_id,
            ma.channel_id, ma.scope_type, ma.scope_key, ma.status, ma.active_slot
        FROM {database}.operations_monitoring_scope AS ms
        JOIN {database}.projects_project AS p ON p.id = ms.project_id
        JOIN {database}.operations_monitoring_assignment AS ma
          ON ma.monitoring_scope_id = ms.id
        WHERE p.business_no = 'E2E-OPS-MON'
        ORDER BY ms.id, ma.id
    """,
}


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required for clean E2E seed verification.")
    return value


def run_manage(*args: str, env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "manage.py", *args, "--settings=config.settings.test"],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
    )


def read_seed_snapshot(cursor: MySQLdb.cursors.Cursor, database_name: str) -> dict[str, tuple]:
    database = f"`{database_name}`"
    snapshot: dict[str, tuple] = {}
    for asset_name, query in SNAPSHOT_QUERIES.items():
        cursor.execute(query.format(database=database))
        rows = tuple(cursor.fetchall())
        if not rows:
            raise RuntimeError(f"Clean seed created no stable {asset_name} fixtures.")
        snapshot[asset_name] = rows
    return snapshot


def main() -> int:
    root_password = required_env("MYSQL_ROOT_PASSWORD")
    database_name = f"meridian_seed_verify_{uuid.uuid4().hex[:12]}"
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise RuntimeError("Generated verification database name is unsafe.")

    connection = MySQLdb.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user="root",
        passwd=root_password,
    )
    connection.autocommit(True)
    cursor = connection.cursor()
    database_created = False
    primary_error: BaseException | None = None

    child_env = os.environ.copy()
    child_env.update(
        {
            "MYSQL_DATABASE": database_name,
            "MYSQL_TEST_DATABASE": database_name,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": root_password,
        }
    )

    try:
        cursor.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        database_created = True
        run_manage("migrate", "--noinput", env=child_env)
        run_manage("seed_e2e_user", env=child_env)

        first_snapshot = read_seed_snapshot(cursor, database_name)

        run_manage("seed_e2e_user", env=child_env)

        second_snapshot = read_seed_snapshot(cursor, database_name)
        changed_assets = [
            asset_name
            for asset_name in first_snapshot
            if second_snapshot[asset_name] != first_snapshot[asset_name]
        ]
        if changed_assets:
            raise RuntimeError(
                "Repeat seed changed stable E2E fixtures: " + ", ".join(changed_assets)
            )

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM `{database_name}`.`authorization_role_assignment`
            WHERE scope_id IS NULL
               OR scope_key <> CONCAT(scope_type, ':', scope_id)
            """
        )
        invalid_scope_count = int(cursor.fetchone()[0])
        if invalid_scope_count:
            raise RuntimeError(
                f"Seed created {invalid_scope_count} role assignments with invalid scope fields."
            )

        print(
            "Clean E2E seed verification passed: "
            f"{len(first_snapshot['role_assignments'])} normalized role assignments "
            f"and {len(first_snapshot)} stable fixture groups."
        )
        return 0
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors: list[tuple[str, BaseException]] = []
        if database_created:
            try:
                cursor.execute(f"DROP DATABASE `{database_name}`")
            except BaseException as cleanup_error:
                cleanup_errors.append(("drop database", cleanup_error))
        for cleanup_name, cleanup in (
            ("close cursor", cursor.close),
            ("close connection", connection.close),
        ):
            try:
                cleanup()
            except BaseException as cleanup_error:
                cleanup_errors.append((cleanup_name, cleanup_error))
        if cleanup_errors and primary_error is None:
            raise cleanup_errors[0][1]
        for cleanup_name, cleanup_error in cleanup_errors:
            print(
                "Clean seed verification cleanup also failed "
                f"while attempting to {cleanup_name}: {cleanup_error}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
