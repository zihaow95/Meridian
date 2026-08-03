"""Verify Phase 6 acceptance seed is stable across two runs on a clean MySQL DB."""

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
    "products": """
        SELECT id, public_id, business_no, lifecycle_status, name
        FROM {database}.products_product_asset
        WHERE business_no LIKE 'P6-PRD-%'
        ORDER BY business_no
    """,
    "product_versions": """
        SELECT v.id, v.public_id, p.business_no, v.version_code, v.status
        FROM {database}.products_product_version AS v
        JOIN {database}.products_product_asset AS p ON p.id = v.product_id
        WHERE p.business_no LIKE 'P6-PRD-%'
        ORDER BY p.business_no, v.version_code
    """,
    "skus": """
        SELECT s.id, s.public_id, s.sku_code, s.status, p.business_no
        FROM {database}.products_sku AS s
        JOIN {database}.products_product_version AS v ON v.id = s.product_version_id
        JOIN {database}.products_product_asset AS p ON p.id = v.product_id
        WHERE p.business_no LIKE 'P6-PRD-%'
        ORDER BY s.sku_code
    """,
    "channels": """
        SELECT c.id, c.public_id, c.channel_code, c.channel_status, s.sku_code
        FROM {database}.products_channel_configuration AS c
        JOIN {database}.products_sku AS s ON s.id = c.sku_id
        WHERE s.sku_code LIKE 'SKU-P6-%'
        ORDER BY s.sku_code, c.channel_code
    """,
    "config_snapshots": """
        SELECT cv.id, cv.public_id, d.definition_code, cv.version_number, cv.status,
               cv.current_published_slot
        FROM {database}.configuration_version AS cv
        JOIN {database}.configuration_definition AS d ON d.id = cv.definition_id
        WHERE d.definition_code IN (
            'NOTIFICATION_TEMPLATE_CATALOG',
            'NOTIFICATION_DELIVERY_POLICY',
            'platform.file_upload'
        )
          AND cv.status = 'PUBLISHED'
        ORDER BY d.definition_code, cv.version_number
    """,
    "document_versions": """
        SELECT dv.id, dv.public_id, d.document_code, dv.version_number, dv.status
        FROM {database}.documents_document_version AS dv
        JOIN {database}.documents_document AS d ON d.id = dv.document_id
        WHERE d.document_code LIKE 'P6-DOC-%'
        ORDER BY d.document_code, dv.version_number
    """,
    "pending_triage": """
        SELECT id, public_id, idempotency_key, processing_status, sha256
        FROM {database}.products_legacy_material_submission
        WHERE idempotency_key LIKE 'phase6-pending-%'
        ORDER BY idempotency_key
    """,
    "notifications": """
        SELECT n.id, n.public_id, n.template_code, n.category, n.level, n.status, n.dedup_key
        FROM {database}.notifications_notification AS n
        JOIN {database}.identity_user AS u ON u.id = n.recipient_id
        WHERE u.login_key = 'e2e-active-user'
          AND n.dedup_key LIKE 'phase6:notify:%'
        ORDER BY n.dedup_key
    """,
    "todos": """
        SELECT t.id, t.public_id, t.dedup_key, t.status, t.todo_type
        FROM {database}.notifications_todo AS t
        JOIN {database}.identity_user AS u ON u.id = t.assignee_id
        WHERE u.login_key = 'e2e-active-user' AND t.dedup_key = 'e2e:todo'
        ORDER BY t.id
    """,
    "pilot_batches": """
        SELECT id, public_id, name, status, purpose,
               planned_participant_count, planned_duration_days
        FROM {database}.pilot_batch
        WHERE name = 'Phase6 Internal Acceptance'
        ORDER BY id
    """,
    "pilot_feedback": """
        SELECT id, public_id, title, severity, status, external_key, version_no
        FROM {database}.pilot_feedback
        WHERE external_key = 'phase6-seed-feedback-1'
        ORDER BY id
    """,
    "pilot_users": """
        SELECT id, public_id, employee_no, status, display_name
        FROM {database}.identity_user
        WHERE employee_no = 'P-E2E-001'
        ORDER BY id
    """,
}


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required for Phase 6 seed verification.")
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
            raise RuntimeError(f"Phase 6 seed created no stable {asset_name} fixtures.")
        snapshot[asset_name] = rows
    return snapshot


def assert_volume_floors(snapshot: dict[str, tuple]) -> None:
    if len(snapshot["products"]) > 20:
        raise RuntimeError("Phase 6 seed exceeded 20 acceptance products.")
    if len(snapshot["document_versions"]) < 120:
        # 100 current + 20 historical extras = 120 version rows
        raise RuntimeError(
            "Phase 6 seed expected at least 120 document versions "
            f"(got {len(snapshot['document_versions'])})."
        )
    if len(snapshot["pending_triage"]) < 10:
        raise RuntimeError("Phase 6 seed expected at least 10 pending triage rows.")
    if len(snapshot["notifications"]) < 6:
        raise RuntimeError("Phase 6 seed expected six category notification rows.")


def main() -> int:
    root_password = required_env("MYSQL_ROOT_PASSWORD")
    database_name = f"meridian_p6_seed_{uuid.uuid4().hex[:12]}"
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
        run_manage("seed_phase6_acceptance", env=child_env)
        first_snapshot = read_seed_snapshot(cursor, database_name)
        assert_volume_floors(first_snapshot)

        run_manage("seed_phase6_acceptance", env=child_env)
        second_snapshot = read_seed_snapshot(cursor, database_name)
        changed = [
            name
            for name in first_snapshot
            if second_snapshot[name] != first_snapshot[name]
        ]
        if changed:
            raise RuntimeError(
                "Repeat Phase 6 seed changed stable fixtures: " + ", ".join(changed)
            )

        print(
            "Clean Phase 6 seed verification passed: "
            f"{len(first_snapshot['products'])} products, "
            f"{len(first_snapshot['document_versions'])} document versions, "
            f"{len(first_snapshot)} stable fixture groups."
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
                "Phase 6 seed verification cleanup also failed "
                f"while attempting to {cleanup_name}: {cleanup_error}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
