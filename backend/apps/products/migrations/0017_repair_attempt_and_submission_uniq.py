"""Append-only settlement repair attempts (attempt_no).

Source_submission uniqueness used to live here too; it is split into 0018 so a
failed unique-key upgrade cannot leave repair DDL half-applied. The historical
filename is kept so databases that already applied 46f65ce's 0017 do not re-run
RemoveConstraint / AddField.
"""

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
    ]
