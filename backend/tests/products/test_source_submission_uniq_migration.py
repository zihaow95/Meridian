"""Upgrade guards for one ProductMaterial per source_submission."""

from __future__ import annotations

import importlib
import uuid

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

repair_migration = importlib.import_module(
    "apps.products.migrations.0017_repair_attempt_and_submission_uniq"
)
submission_migration = importlib.import_module(
    "apps.products.migrations.0018_product_material_source_submission_uniq"
)

REPAIR_NAME = "0017_repair_attempt_and_submission_uniq"
SUBMISSION_NAME = "0018_product_material_source_submission_uniq"
CONSTRAINT = "products_material_source_submission_uniq"


def _constraint_exists() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
              AND constraint_name = %s
            """,
            [CONSTRAINT],
        )
        return cursor.fetchone()[0] >= 1


def test_repair_migration_does_not_touch_source_submission_uniqueness() -> None:
    """Repair retry and submission uniqueness have different upgrade risk."""

    assert all(
        not (
            isinstance(operation, migrations.AddConstraint)
            and operation.constraint.name == CONSTRAINT
        )
        for operation in repair_migration.Migration.operations
    )


def test_submission_duplicate_guard_runs_before_any_ddl() -> None:
    """MySQL cannot roll back applied DDL, so the stop-the-line check goes first."""

    operations = submission_migration.Migration.operations
    guard_index = next(
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.RunPython)
        and operation.code is submission_migration.refuse_duplicate_source_submissions
    )
    first_schema_index = next(
        index
        for index, operation in enumerate(operations)
        if not isinstance(operation, migrations.RunPython)
    )

    assert guard_index < first_schema_index


@pytest.mark.django_db(transaction=True)
def test_old_state_upgrade_fails_leaves_no_half_applied_constraint_then_reruns(
    organization,
    active_user,
    change_set,
    controlled_document_version,
) -> None:
    """Duplicate old rows fail before DDL; settling them lets the same migration finish."""

    executor = MigrationExecutor(connection)
    before = ("products", REPAIR_NAME)
    target = ("products", SUBMISSION_NAME)
    products_leaf = [node for node in executor.loader.graph.leaf_nodes() if node[0] == "products"]

    try:
        executor.migrate([before])
        assert not _constraint_exists()

        state = executor.loader.project_state([before])
        apps = state.apps
        ProductMaterial = apps.get_model("products", "ProductMaterial")
        LegacyMaterialSubmission = apps.get_model("products", "LegacyMaterialSubmission")

        version = controlled_document_version()
        submission = LegacyMaterialSubmission.objects.create(
            organization_id=organization.id,
            document_version_id=version.id,
            owner_type="PRODUCT",
            owner_id=change_set.product_id,
            submitted_by_id=active_user.id,
            sha256=version.file_object.sha256,
            idempotency_key=f"mig-dup-{uuid.uuid4().hex[:12]}",
            processing_status="VERIFIED",
            public_id=uuid.uuid4(),
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        for index, type_code in enumerate(("PRODUCT_LABEL", "PRODUCT_MANUAL"), start=1):
            doc = controlled_document_version()
            ProductMaterial.objects.create(
                organization_id=organization.id,
                change_set_id=change_set.id,
                owner_type="PRODUCT",
                owner_id=change_set.product_id,
                material_type_code=type_code,
                document_version_id=doc.id,
                purpose="",
                sensitivity_level="INTERNAL",
                material_status="DRAFT",
                version_no=index,
                source_submission_id=submission.id,
                public_id=uuid.uuid4(),
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )

        executor.loader.build_graph()
        with pytest.raises(RuntimeError, match="source_submission"):
            executor.migrate([target])

        assert not _constraint_exists()
        applied = MigrationExecutor(connection).loader.applied_migrations
        assert target not in applied

        ProductMaterial.objects.filter(source_submission_id=submission.id).order_by(
            "id"
        ).last().delete()

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target])

        assert _constraint_exists()
        assert target in MigrationExecutor(connection).loader.applied_migrations
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(products_leaf or [target])
