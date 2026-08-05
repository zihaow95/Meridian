"""Append-only settlement repair attempts, plus source_submission uniq in state.

Database history from 46f65ce already applied this migration name with both the
repair DDL and products_material_source_submission_uniq. The filename and the
rendered model state therefore keep owning that unique constraint.

The physical ADD is deferred to 0018 (after a duplicate refuse) so a failed
unique-key upgrade cannot leave repair DDL half-applied on a greenfield
database. database_operations for the constraint are empty here: old installs
already have the index; new installs receive it from 0018.
"""

from django.db import migrations, models

SOURCE_SUBMISSION_CONSTRAINT = "products_material_source_submission_uniq"


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
        # State ownership matches the original 46f65ce 0017. No database DDL
        # here: dropping/re-adding on reverse would desync already-upgraded DBs.
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
            database_operations=[],
        ),
    ]
