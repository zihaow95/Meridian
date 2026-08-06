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
    # The material confirmation loop is the one the seed itself drives end to end:
    # request, projection, decision, settlement. Snapshotting only 'e2e:todo' would
    # report a stable seed while an APPROVED material still wore an OPEN todo.
    "confirmation_todos": """
        SELECT t.dedup_key, t.status, t.open_slot, t.action_code
        FROM {database}.notifications_todo AS t
        WHERE t.dedup_key LIKE 'material\\_confirmation:%'
        ORDER BY t.dedup_key
    """,
    # Keyed, not joined: one notice serves one ask, so a replayed request can leave a
    # sibling todo row with no notice of its own while the ask is properly closed.
    "confirmation_notifications": """
        SELECT n.dedup_key, n.status, n.close_reason
        FROM {database}.notifications_notification AS n
        WHERE n.dedup_key LIKE 'notify:material\\_confirmation:%'
        ORDER BY n.dedup_key, n.id
    """,
    "projection_events": """
        SELECT e.event_type, e.aggregate_type, e.status, e.attempt_count,
               e.last_error_code
        FROM {database}.platform_outbox_event AS e
        WHERE e.event_type IN ('todo.requested', 'material_confirmation.decided')
        ORDER BY e.occurred_at, e.id
    """,
    "projection_receipts": """
        SELECT e.event_type, r.consumer_code
        FROM {database}.platform_consumer_receipt AS r
        JOIN {database}.platform_outbox_event AS e ON e.id = r.event_id
        WHERE e.event_type IN ('todo.requested', 'material_confirmation.decided')
        ORDER BY e.occurred_at, r.id
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


def assert_projection_loop_settled(snapshot: dict[str, tuple]) -> None:
    """The seed must hand back a settled loop, not a retryable intention.

    Phase 6 has no Celery worker, so an event left PENDING is stuck, and a decided
    confirmation would keep an OPEN todo and an UNREAD notice forever.
    """

    problems: list[str] = []
    for dedup_key, status, open_slot, _action_code in snapshot["confirmation_todos"]:
        if status not in {"COMPLETED", "CANCELLED"}:
            problems.append(f"todo {dedup_key} is {status}")
        if open_slot is not None:
            problems.append(f"todo {dedup_key} still holds the open slot")
    for dedup_key, status, _close_reason in snapshot["confirmation_notifications"]:
        if status != "CLOSED":
            problems.append(f"notification for {dedup_key} is {status}")

    receipts_by_type: dict[str, int] = {}
    for event_type, _consumer_code in snapshot["projection_receipts"]:
        receipts_by_type[event_type] = receipts_by_type.get(event_type, 0) + 1
    events_by_type: dict[str, int] = {}
    for event_type, _aggregate_type, status, attempts, last_error in snapshot["projection_events"]:
        events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
        if status != "PUBLISHED":
            problems.append(
                f"{event_type} is {status} after {attempts} attempt(s) "
                f"(last error {last_error or 'NONE'})"
            )
    for event_type, count in events_by_type.items():
        if receipts_by_type.get(event_type, 0) < count:
            problems.append(
                f"{event_type} has {receipts_by_type.get(event_type, 0)} receipt(s) "
                f"for {count} event(s)"
            )

    if problems:
        raise RuntimeError(
            "Phase 6 seed left the notification projection loop open: " + "; ".join(problems)
        )


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
        assert_projection_loop_settled(first_snapshot)

        run_manage("seed_phase6_acceptance", env=child_env)
        second_snapshot = read_seed_snapshot(cursor, database_name)
        assert_projection_loop_settled(second_snapshot)
        changed = [name for name in first_snapshot if second_snapshot[name] != first_snapshot[name]]
        if changed:
            raise RuntimeError("Repeat Phase 6 seed changed stable fixtures: " + ", ".join(changed))

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
