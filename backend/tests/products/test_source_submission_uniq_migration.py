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
BASELINE_NAME = "0016_materialconfirmationsettlementrepair"
CONSTRAINT = "products_material_source_submission_uniq"
FK_HELPER_INDEX = "products_material_source_submission_fk"


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


def _index_names() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT index_name FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
            """
        )
        return {row[0] for row in cursor.fetchall()}


def _helper_index_exists() -> bool:
    return FK_HELPER_INDEX in _index_names()


def _strip_source_submission_uniq_leaving_fk() -> bool:
    """Remove the unique index left behind by 0018's no-op reverse.

    Returns True when this helper created products_material_source_submission_fk.
    """

    if not _constraint_exists():
        return False
    created_helper = False
    with connection.cursor() as cursor:
        if not _helper_index_exists():
            cursor.execute(
                "ALTER TABLE products_product_material "
                f"ADD INDEX {FK_HELPER_INDEX} (source_submission_id)"
            )
            created_helper = True
        cursor.execute(f"ALTER TABLE products_product_material DROP INDEX {CONSTRAINT}")
    return created_helper


def _drop_helper_index_if_present() -> None:
    if not _helper_index_exists():
        return
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE products_product_material DROP INDEX {FK_HELPER_INDEX}")


def _state_has_constraint(migration_name: str) -> bool:
    executor = MigrationExecutor(connection)
    state = executor.loader.project_state([("products", migration_name)])
    model = state.apps.get_model("products", "ProductMaterial")
    return any(constraint.name == CONSTRAINT for constraint in model._meta.constraints)


def test_0017_owns_constraint_in_state_with_noop_forward_and_conditional_reverse() -> None:
    """46f65ce ownership stays on 0017; reverse must clear the MySQL unique index."""

    state_ops = [
        operation
        for operation in repair_migration.Migration.operations
        if isinstance(operation, migrations.SeparateDatabaseAndState)
    ]
    assert len(state_ops) == 1
    db_ops = state_ops[0].database_operations
    assert len(db_ops) == 1
    assert isinstance(db_ops[0], migrations.RunPython)
    assert db_ops[0].code is repair_migration.noop_source_submission_uniq
    assert db_ops[0].reverse_code is repair_migration.remove_source_submission_uniq_if_present
    assert any(
        isinstance(operation, migrations.AddConstraint) and operation.constraint.name == CONSTRAINT
        for operation in state_ops[0].state_operations
    )


def test_0018_refuses_duplicates_before_adding_and_never_drops_on_reverse() -> None:
    """MySQL cannot roll back DDL; reverse must not steal 0017's constraint."""

    operations = submission_migration.Migration.operations
    assert len(operations) == 2
    assert isinstance(operations[0], migrations.RunPython)
    assert operations[0].code is submission_migration.refuse_duplicate_source_submissions
    assert isinstance(operations[1], migrations.RunPython)
    assert operations[1].code is submission_migration.add_source_submission_uniq_if_missing
    assert operations[1].reverse_code is migrations.RunPython.noop


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
    created_helper = False

    try:
        executor.migrate([before])
        # 0018 reverse is intentionally a no-op, so a DB that once reached leaf may
        # still carry the unique index. Strip it to recreate the greenfield-after-0017
        # shape that 0018 is responsible for upgrading.
        created_helper = _strip_source_submission_uniq_leaving_fk()
        assert not _constraint_exists()
        assert _state_has_constraint(REPAIR_NAME)

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
        if created_helper:
            _drop_helper_index_if_present()
        assert not _helper_index_exists()


@pytest.mark.django_db(transaction=True)
def test_legacy_46f65ce_0017_with_constraint_survives_0018_forward_reverse_forward() -> None:
    """Old combined 0017 left the unique index; 0018 must not take ownership away on reverse."""

    executor = MigrationExecutor(connection)
    before = ("products", REPAIR_NAME)
    target = ("products", SUBMISSION_NAME)
    products_leaf = [node for node in executor.loader.graph.leaf_nodes() if node[0] == "products"]

    try:
        executor.migrate([before])
        # Simulate 46f65ce: same migration name already applied and the unique index exists.
        assert before in MigrationExecutor(connection).loader.applied_migrations
        assert target not in MigrationExecutor(connection).loader.applied_migrations
        assert _state_has_constraint(REPAIR_NAME)

        with connection.schema_editor() as schema_editor:
            from django.apps import apps as django_apps

            submission_migration.add_source_submission_uniq_if_missing(django_apps, schema_editor)
        assert _constraint_exists()

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target])

        assert _constraint_exists()
        assert target in MigrationExecutor(connection).loader.applied_migrations
        assert _state_has_constraint(SUBMISSION_NAME)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([before])

        applied = MigrationExecutor(connection).loader.applied_migrations
        assert before in applied
        assert target not in applied
        assert _constraint_exists(), (
            "reversing 0018 must not drop a constraint created by legacy 0017"
        )
        assert _state_has_constraint(REPAIR_NAME), (
            "after reverse, project state at 0017 must still own the constraint"
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target])

        applied = MigrationExecutor(connection).loader.applied_migrations
        assert before in applied
        assert target in applied
        assert _constraint_exists()
        assert _state_has_constraint(SUBMISSION_NAME)
        assert not _helper_index_exists()
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(products_leaf or [target])
        _drop_helper_index_if_present()


@pytest.mark.django_db(transaction=True)
def test_rolling_back_through_0016_drops_constraint_then_0018_restores_it() -> None:
    """0018 → 0016 must clear MySQL uniqueness; 0016 → 0018 must restore without drift."""

    executor = MigrationExecutor(connection)
    baseline = ("products", BASELINE_NAME)
    target = ("products", SUBMISSION_NAME)
    products_leaf = [node for node in executor.loader.graph.leaf_nodes() if node[0] == "products"]

    try:
        executor.migrate([target])
        assert _constraint_exists()
        index_baseline = _index_names()
        assert FK_HELPER_INDEX not in index_baseline

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([baseline])

        applied = MigrationExecutor(connection).loader.applied_migrations
        assert baseline in applied
        assert ("products", REPAIR_NAME) not in applied
        assert target not in applied
        assert not _constraint_exists()
        assert not _state_has_constraint(BASELINE_NAME)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([target])

        applied = MigrationExecutor(connection).loader.applied_migrations
        assert ("products", REPAIR_NAME) in applied
        assert target in applied
        assert _constraint_exists()
        assert _state_has_constraint(SUBMISSION_NAME)
        assert _index_names() == index_baseline
        assert FK_HELPER_INDEX not in _index_names()
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(products_leaf or [target])
        _drop_helper_index_if_present()
