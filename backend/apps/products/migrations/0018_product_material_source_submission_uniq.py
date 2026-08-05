"""Ensure ProductMaterial.source_submission uniqueness on the database.

0017 owns the constraint in Django project state (including databases that
applied 46f65ce's combined 0017). This migration only:

1. refuses colliding non-null source_submission values before any DDL;
2. adds the unique constraint when it is missing (greenfield after rewritten 0017);
3. drops the temporary FK helper index 0017 reverse may have left behind.

Reverse is a no-op on the database. Removing the index here would leave
"0017 applied, constraint absent" drift for installs where 46f65ce's 0017
created the constraint; 0017 reverse is responsible for dropping it when
rolling back past 0017.
"""

from django.db import migrations, models
from django.db.models import Count

CONSTRAINT_NAME = "products_material_source_submission_uniq"
FK_HELPER_INDEX = "products_material_source_submission_fk"


def refuse_duplicate_source_submissions(apps, schema_editor) -> None:
    """Stop if non-null source_submission values already collide.

    Runs before any DDL so a stop leaves the schema exactly as it was.
    """

    ProductMaterial = apps.get_model("products", "ProductMaterial")
    duplicates = list(
        ProductMaterial.objects.exclude(source_submission_id=None)
        .values("source_submission_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .order_by("source_submission_id")
    )
    if not duplicates:
        return

    detail = "; ".join(
        f"source_submission_id={row['source_submission_id']} count={row['total']}"
        for row in duplicates
    )
    raise RuntimeError(
        "Duplicate ProductMaterial.source_submission values exist, so the "
        "uniqueness cannot be enforced without discarding a material fact. "
        "Settle the extras by hand, then re-run this migration. "
        f"Offenders: {detail}"
    )


def _constraint_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
              AND constraint_name = %s
            """,
            [CONSTRAINT_NAME],
        )
        return cursor.fetchone()[0] >= 1


def add_source_submission_uniq_if_missing(apps, schema_editor) -> None:
    if not _constraint_exists(schema_editor):
        ProductMaterial = apps.get_model("products", "ProductMaterial")
        constraint = models.UniqueConstraint(
            fields=("source_submission",),
            name=CONSTRAINT_NAME,
        )
        schema_editor.add_constraint(ProductMaterial, constraint)
    _drop_fk_helper_index_if_unique_covers(schema_editor)


def _drop_fk_helper_index_if_unique_covers(schema_editor) -> None:
    if not _constraint_exists(schema_editor):
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'products_product_material'
              AND index_name = %s
            """,
            [FK_HELPER_INDEX],
        )
        if cursor.fetchone()[0] == 0:
            return
        cursor.execute(
            f"ALTER TABLE products_product_material DROP INDEX {FK_HELPER_INDEX}"
        )


class Migration(migrations.Migration):
    # RunPython performs DDL (ADD/DROP INDEX). MySQL cannot run that inside the
    # per-migration transaction Django would otherwise open.
    atomic = False

    dependencies = [
        ("products", "0017_repair_attempt_and_submission_uniq"),
    ]

    operations = [
        migrations.RunPython(
            refuse_duplicate_source_submissions,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            add_source_submission_uniq_if_missing,
            migrations.RunPython.noop,
        ),
    ]
