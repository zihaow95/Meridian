# Related-name alignment only; existing indexes remain on MySQL.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("opportunities", "0005_remove_opportunitymember_opportunities_member_active_uniq_and_more"),
        ("products", "0003_product_profile_core"),
        ("projects", "0003_product_profile_core"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="productchangeset",
                    name="product",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_sets",
                        to="products.productasset",
                    ),
                ),
                migrations.AlterField(
                    model_name="productchangeset",
                    name="project_candidate",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="product_change_sets",
                        to="opportunities.projectcandidate",
                    ),
                ),
                migrations.AlterField(
                    model_name="productchangeset",
                    name="target_product_asset",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="targeted_change_sets",
                        to="products.productasset",
                    ),
                ),
                migrations.RemoveIndex(
                    model_name="productchangeset",
                    name="products_pr_product_81d130_idx",
                ),
                migrations.AddIndex(
                    model_name="productchangeset",
                    index=models.Index(
                        fields=["product", "status"],
                        name="products_pr_product_81d130_idx",
                    ),
                ),
            ],
        ),
    ]
