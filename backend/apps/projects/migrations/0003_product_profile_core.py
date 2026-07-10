# Generated manually for phase 3 product profile core migration.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_product_profile_core"),
        ("projects", "0002_remove_projectmember_projects_member_active_uniq_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="product_draft",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="products.productchangeset",
            ),
        ),
    ]
