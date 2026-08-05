"""One ProductMaterial version per legacy source_submission.

MySQL cannot roll back DDL. Refuse colliding non-null source_submission values
before adding the unique constraint so a stopped upgrade leaves no half-applied
schema. Environments that already gained the constraint from an earlier combined
0017 skip the ADD when the index is present.
"""

from django.db import migrations, models
from django.db.models import Count

CONSTRAINT_NAME = "products_material_source_submission_uniq"


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
    if _constraint_exists(schema_editor):
        return
    ProductMaterial = apps.get_model("products", "ProductMaterial")
    constraint = models.UniqueConstraint(
        fields=("source_submission",),
        name=CONSTRAINT_NAME,
    )
    schema_editor.add_constraint(ProductMaterial, constraint)


def remove_source_submission_uniq_if_present(apps, schema_editor) -> None:
    if not _constraint_exists(schema_editor):
        return
    ProductMaterial = apps.get_model("products", "ProductMaterial")
    constraint = models.UniqueConstraint(
        fields=("source_submission",),
        name=CONSTRAINT_NAME,
    )
    schema_editor.remove_constraint(ProductMaterial, constraint)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0017_repair_attempt_and_submission_uniq"),
    ]

    operations = [
        migrations.RunPython(
            refuse_duplicate_source_submissions,
            migrations.RunPython.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="productmaterial",
                    constraint=models.UniqueConstraint(
                        fields=("source_submission",),
                        name=CONSTRAINT_NAME,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    add_source_submission_uniq_if_missing,
                    remove_source_submission_uniq_if_present,
                ),
            ],
        ),
    ]
