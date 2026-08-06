"""Append-only settlement repair attempts, plus source_submission uniq in state.

Database history from 46f65ce already applied this migration name with both the
repair DDL and products_material_source_submission_uniq. The filename and the
rendered model state therefore keep owning that unique constraint.

The physical ADD stays in 0018 (after a duplicate refuse) so a failed unique-key
upgrade cannot leave repair DDL half-applied on a greenfield database. Forward
database work for the constraint is a no-op; reverse conditionally drops the
MySQL unique index so rolling back to 0016 cannot leave "state says absent,
database still unique".
"""

from django.db import migrations, models

SOURCE_SUBMISSION_CONSTRAINT = "products_material_source_submission_uniq"
SOURCE_SUBMISSION_FK_HELPER_INDEX = "products_material_source_submission_fk"


def noop_source_submission_uniq(apps, schema_editor) -> None:
    return None


def source_submission_constraint_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
              AND constraint_name = %s
            """,
            [SOURCE_SUBMISSION_CONSTRAINT],
        )
        return cursor.fetchone()[0] >= 1


def _indexes_on_source_submission(schema_editor) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT index_name FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
              AND column_name = 'source_submission_id'
            """
        )
        return {row[0] for row in cursor.fetchall()}


def remove_source_submission_uniq_if_present(apps, schema_editor) -> None:
    """Drop the unique index when leaving 0017 so 0016 matches project state."""

    if not source_submission_constraint_exists(schema_editor):
        return

    indexes = _indexes_on_source_submission(schema_editor)
    others = indexes - {SOURCE_SUBMISSION_CONSTRAINT}
    with schema_editor.connection.cursor() as cursor:
        if not others:
            # InnoDB needs some index on the FK column after the unique drop.
            cursor.execute(
                f"ALTER TABLE products_product_material "
                f"ADD INDEX {SOURCE_SUBMISSION_FK_HELPER_INDEX} (source_submission_id)"
            )

    ProductMaterial = apps.get_model("products", "ProductMaterial")
    constraint = models.UniqueConstraint(
        fields=("source_submission",),
        name=SOURCE_SUBMISSION_CONSTRAINT,
    )
    schema_editor.remove_constraint(ProductMaterial, constraint)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0016_materialconfirmationsettlementrepair"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="materialconfirmationsettlementrepair",
            name="products_material_repair_uniq",
        ),
        migrations.AddField(
            model_name="materialconfirmationsettlementrepair",
            name="attempt_no",
            field=models.PositiveIntegerField(default=1),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="materialconfirmationsettlementrepair",
            constraint=models.UniqueConstraint(
                fields=("confirmation", "todo_public_id", "attempt_no"),
                name="products_material_repair_attempt_uniq",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="productmaterial",
                    constraint=models.UniqueConstraint(
                        fields=("source_submission",),
                        name=SOURCE_SUBMISSION_CONSTRAINT,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    noop_source_submission_uniq,
                    remove_source_submission_uniq_if_present,
                    atomic=False,
                ),
            ],
        ),
    ]
