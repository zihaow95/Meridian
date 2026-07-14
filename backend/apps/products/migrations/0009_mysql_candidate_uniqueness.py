# MySQL does not enforce partial unique constraints; use nullable UNIQUE (multiple NULLs allowed).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0008_import_batches"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="productchangeset",
            name="products_draft_candidate_uniq",
        ),
        migrations.AddConstraint(
            model_name="productchangeset",
            constraint=models.UniqueConstraint(
                fields=("project_candidate",),
                name="products_draft_candidate_uniq",
            ),
        ),
    ]
