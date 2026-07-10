# Generated manually for phase 3 product profile core migration.

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def map_product_change_draft_types(apps, schema_editor) -> None:
    change_set = apps.get_model("products", "ProductDraft")
    change_set.objects.filter(change_type="PRODUCT_CHANGE").update(change_type="ITERATION")


def backfill_change_set_project_ids(apps, schema_editor) -> None:
    change_set = apps.get_model("products", "ProductDraft")
    project = apps.get_model("projects", "Project")
    for row in change_set.objects.filter(project_id__isnull=True):
        linked = project.objects.filter(product_draft_id=row.id).first()
        if linked is not None:
            row.project_id = linked.id
            row.save(update_fields=["project_id"])


def _column_names(schema_editor, table_name: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def add_product_asset_profile_columns(apps, schema_editor) -> None:
    product_asset = apps.get_model("products", "ProductAsset")
    table_name = product_asset._meta.db_table
    existing = _column_names(schema_editor, table_name)
    fields = (
        ("brand_code", models.CharField(blank=True, default="", max_length=40)),
        ("category_code", models.CharField(blank=True, default="", max_length=40)),
        ("retired_at", models.DateTimeField(blank=True, null=True)),
    )
    for field_name, field in fields:
        if field_name in existing:
            continue
        field.set_attributes_from_name(field_name)
        schema_editor.add_field(product_asset, field)


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0002_remove_user_identity_user_org_employee_no_uniq_and_more"),
        ("opportunities", "0005_remove_opportunitymember_opportunities_member_active_uniq_and_more"),
        ("products", "0002_initial"),
        ("projects", "0002_remove_projectmember_projects_member_active_uniq_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_product_asset_profile_columns, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="productasset",
                    name="brand_code",
                    field=models.CharField(blank=True, default="", max_length=40),
                ),
                migrations.AddField(
                    model_name="productasset",
                    name="category_code",
                    field=models.CharField(blank=True, default="", max_length=40),
                ),
                migrations.AddField(
                    model_name="productasset",
                    name="retired_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
        migrations.RenameField(
            model_name="productdraft",
            old_name="draft_type",
            new_name="change_type",
        ),
        migrations.RenameField(
            model_name="productdraft",
            old_name="product_asset",
            new_name="product",
        ),
        migrations.AddField(
            model_name="productdraft",
            name="approval_basis_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="approval_basis_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="base_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="change_scope",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="completeness_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("COMPLETE", "Complete"),
                    ("PARTIAL", "Partial"),
                    ("NEEDS_SUPPLEMENT", "Needs supplement"),
                ],
                max_length=24,
                default="",
            ),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="migration_batch_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="product_change_sets",
                to="projects.project",
            ),
        ),
        migrations.AddField(
            model_name="productdraft",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="productdraft",
            name="change_type",
            field=models.CharField(
                choices=[
                    ("NEW_PRODUCT", "New product"),
                    ("ITERATION", "Product iteration"),
                    ("LEGACY_BASELINE", "Legacy baseline"),
                    ("CORRECTION", "Correction"),
                ],
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="productdraft",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("SUBMITTED", "Submitted"),
                    ("LOCKED", "Locked"),
                    ("IN_CONFIRMATION", "In confirmation"),
                    ("APPROVED", "Approved"),
                    ("PUBLISHED", "Published"),
                    ("REJECTED", "Rejected"),
                ],
                default="DRAFT",
                max_length=24,
            ),
        ),
        migrations.RunPython(map_product_change_draft_types, migrations.RunPython.noop),
        migrations.RunPython(backfill_change_set_project_ids, migrations.RunPython.noop),
        migrations.RenameModel(
            old_name="ProductDraft",
            new_name="ProductChangeSet",
        ),
        migrations.AlterModelTable(
            name="productchangeset",
            table="products_product_change_set",
        ),
        migrations.CreateModel(
            name="ProductVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("version_code", models.CharField(max_length=40)),
                ("version_name", models.CharField(max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("PENDING_CONFIRMATION", "Pending confirmation"),
                            ("APPROVED_PENDING_EFFECTIVE", "Approved pending effective"),
                            ("EFFECTIVE", "Effective"),
                            ("INACTIVE", "Inactive"),
                        ],
                        max_length=32,
                    ),
                ),
                ("definition_summary", models.TextField(blank=True, default="")),
                ("shelf_life_value", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("shelf_life_unit", models.CharField(blank=True, default="", max_length=16)),
                ("storage_condition", models.TextField(blank=True, default="")),
                ("standard_code", models.CharField(blank=True, default="", max_length=80)),
                ("effective_from", models.DateTimeField(blank=True, null=True)),
                ("effective_to", models.DateTimeField(blank=True, null=True)),
                ("approval_basis_type", models.CharField(blank=True, default="", max_length=40)),
                ("approval_basis_id", models.BigIntegerField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "change_set",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="draft_versions",
                        to="products.productchangeset",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="identity.organization",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versions",
                        to="products.productasset",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="published_product_versions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "supersedes_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="superseded_by_versions",
                        to="products.productversion",
                    ),
                ),
            ],
            options={
                "db_table": "products_product_version",
            },
        ),
        migrations.AddField(
            model_name="productchangeset",
            name="base_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="iteration_change_sets",
                to="products.productversion",
            ),
        ),
        migrations.AddField(
            model_name="productasset",
            name="primary_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="primary_for_assets",
                to="products.productversion",
            ),
        ),
        migrations.CreateModel(
            name="ProductVersionScope",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                (
                    "scope_type",
                    models.CharField(
                        choices=[("GLOBAL", "Global"), ("CHANNEL", "Channel")],
                        max_length=16,
                    ),
                ),
                ("channel_code", models.CharField(blank=True, default="", max_length=40)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_to", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PLANNED", "Planned"),
                            ("EFFECTIVE", "Effective"),
                            ("ENDED", "Ended"),
                        ],
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="identity.organization",
                    ),
                ),
                (
                    "product_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="scopes",
                        to="products.productversion",
                    ),
                ),
            ],
            options={
                "db_table": "products_product_version_scope",
            },
        ),
        migrations.CreateModel(
            name="SKU",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("sku_code", models.CharField(max_length=40)),
                ("name", models.CharField(max_length=200)),
                ("specification", models.CharField(blank=True, default="", max_length=160)),
                ("net_content_value", models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ("net_content_unit", models.CharField(blank=True, default="", max_length=20)),
                ("sales_unit", models.CharField(blank=True, default="", max_length=40)),
                ("inner_packaging", models.TextField(blank=True, default="")),
                ("outer_packaging", models.TextField(blank=True, default="")),
                ("case_pack_relation", models.CharField(blank=True, default="", max_length=100)),
                ("barcode", models.CharField(blank=True, default="", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("INACTIVE", "Inactive")],
                        default="DRAFT",
                        max_length=20,
                    ),
                ),
                ("effective_from", models.DateTimeField(blank=True, null=True)),
                ("effective_to", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="identity.organization",
                    ),
                ),
                (
                    "product_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="skus",
                        to="products.productversion",
                    ),
                ),
                (
                    "supersedes_sku",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="superseded_by_skus",
                        to="products.sku",
                    ),
                ),
            ],
            options={
                "db_table": "products_sku",
            },
        ),
        migrations.CreateModel(
            name="ChannelConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ("channel_code", models.CharField(max_length=40)),
                ("configuration_version", models.PositiveIntegerField()),
                (
                    "suggested_retail_price",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
                ),
                ("channel_selling_points", models.TextField(blank=True, default="")),
                (
                    "channel_status",
                    models.CharField(
                        choices=[
                            ("PLANNED", "Planned"),
                            ("ON_SALE", "On sale"),
                            ("SUSPENDED", "Suspended"),
                            ("OFF_SALE", "Off sale"),
                        ],
                        max_length=24,
                    ),
                ),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_to", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "change_set",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="channel_configurations",
                        to="products.productchangeset",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="identity.organization",
                    ),
                ),
                (
                    "sku",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="channel_configurations",
                        to="products.sku",
                    ),
                ),
                (
                    "supersedes_config",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="superseded_by_configs",
                        to="products.channelconfiguration",
                    ),
                ),
            ],
            options={
                "db_table": "products_channel_configuration",
            },
        ),
        migrations.AddIndex(
            model_name="productasset",
            index=models.Index(fields=["organization", "lifecycle_status", "category_code"], name="products_pr_organiz_fdd403_idx"),
        ),
        migrations.AddIndex(
            model_name="productasset",
            index=models.Index(fields=["name"], name="products_pr_name_17a43a_idx"),
        ),
        migrations.AddIndex(
            model_name="productasset",
            index=models.Index(fields=["brand_code"], name="products_pr_brand_c_40ca97_idx"),
        ),
        migrations.AddIndex(
            model_name="productchangeset",
            index=models.Index(fields=["project", "status"], name="products_pr_project_132b56_idx"),
        ),
        migrations.AddIndex(
            model_name="productversion",
            index=models.Index(fields=["product", "status"], name="products_pr_product_db2117_idx"),
        ),
        migrations.AddIndex(
            model_name="productversion",
            index=models.Index(fields=["organization", "status", "updated_at"], name="products_pr_organiz_df0be6_idx"),
        ),
        migrations.AddConstraint(
            model_name="productversion",
            constraint=models.UniqueConstraint(fields=("product", "version_code"), name="products_version_product_code_uniq"),
        ),
        migrations.AddIndex(
            model_name="productversionscope",
            index=models.Index(fields=["product_version", "status"], name="products_pr_product_c0371b_idx"),
        ),
        migrations.AddIndex(
            model_name="productversionscope",
            index=models.Index(fields=["organization", "scope_type", "channel_code"], name="products_pr_organiz_7f6d03_idx"),
        ),
        migrations.AddIndex(
            model_name="sku",
            index=models.Index(fields=["product_version", "status"], name="products_sk_product_67e6e2_idx"),
        ),
        migrations.AddIndex(
            model_name="sku",
            index=models.Index(fields=["organization", "barcode"], name="products_sk_organiz_7e66dd_idx"),
        ),
        migrations.AddIndex(
            model_name="sku",
            index=models.Index(fields=["product_version", "name", "specification"], name="products_sk_product_5fcd2d_idx"),
        ),
        migrations.AddConstraint(
            model_name="sku",
            constraint=models.UniqueConstraint(fields=("organization", "sku_code"), name="products_sku_org_code_uniq"),
        ),
        migrations.AddIndex(
            model_name="channelconfiguration",
            index=models.Index(fields=["sku", "channel_code", "channel_status"], name="products_ch_sku_id_0b4c6b_idx"),
        ),
        migrations.AddIndex(
            model_name="channelconfiguration",
            index=models.Index(fields=["organization", "channel_code"], name="products_ch_organiz_4503a2_idx"),
        ),
        migrations.AddConstraint(
            model_name="channelconfiguration",
            constraint=models.UniqueConstraint(
                fields=("sku", "channel_code", "configuration_version"),
                name="products_channel_config_version_uniq",
            ),
        ),
        migrations.CreateModel(
            name="ProductDraft",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("products.productchangeset",),
        ),
    ]
