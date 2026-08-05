"""Append-only repair attempts and one material per source submission."""

from django.db import migrations, models


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
        migrations.AddConstraint(
            model_name="productmaterial",
            constraint=models.UniqueConstraint(
                fields=("source_submission",),
                name="products_material_source_submission_uniq",
            ),
        ),
    ]
