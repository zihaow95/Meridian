"""Move product materials from a frozen enum to configuration-driven codes.

The rename itself is mechanical. What is not mechanical is the data: a row
written with a code this migration cannot account for would silently become a
material type nobody configured, so the migration refuses to run instead.
MySQL cannot roll back applied DDL, so that check runs before any schema
operation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

KNOWN_LEGACY_MATERIAL_TYPES = frozenset(
    {
        "INNER_PACKAGING",
        "OUTER_PACKAGING",
        "LABEL",
        "DESIGN_SOURCE",
        "CHANNEL_IMAGE",
        "APPROVED_PRINT",
    }
)


def assert_material_types_are_mappable(*, observed_types: Iterable[str]) -> None:
    unknown = sorted({value for value in observed_types if value not in KNOWN_LEGACY_MATERIAL_TYPES})
    if unknown:
        raise RuntimeError(
            "Cannot migrate products_product_material: these material_type values are "
            f"not part of the known legacy vocabulary: {', '.join(unknown)}. "
            "Add them to the material requirements configuration and to "
            "KNOWN_LEGACY_MATERIAL_TYPES before re-running this migration."
        )


def reject_unmappable_material_types(apps, schema_editor) -> None:
    material_model = apps.get_model("products", "ProductMaterial")
    observed = material_model.objects.values_list("material_type", flat=True).distinct()
    assert_material_types_are_mappable(observed_types=observed)


def assert_legacy_material_confirmations_are_absent(*, linked_count: int) -> None:
    """Refuse to guess what an attribute-group decision meant about a file.

    `ProductMaterial.confirmation` pointed at `AttributeConfirmation`, whose
    content hash covers attribute values, not file bytes. Such a row therefore
    cannot prove a professional reviewed the document, and turning it into an
    approval in `products_material_confirmation` would fabricate one. No writer
    for the column has ever existed, so a non-zero count means unexpected data
    that a human must classify.
    """

    if linked_count:
        raise RuntimeError(
            f"{linked_count} product material rows carry a legacy attribute confirmation. "
            "There is no rule that proves such a decision reviewed the file bytes, so it "
            "cannot be replayed into products_material_confirmation. Decide each row by "
            "hand, then re-run this migration."
        )


def reject_legacy_material_confirmations(apps, schema_editor) -> None:
    material_model = apps.get_model("products", "ProductMaterial")
    assert_legacy_material_confirmations_are_absent(
        linked_count=material_model.objects.filter(confirmation__isnull=False).count()
    )


def noop(apps, schema_editor) -> None:
    """Reversing a guard has nothing to undo."""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0003_catalogued_upload_metadata"),
        ("identity", "0002_remove_user_identity_user_org_employee_no_uniq_and_more"),
        ("products", "0012_legacy_material_intake"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(reject_unmappable_material_types, noop),
        migrations.RunPython(reject_legacy_material_confirmations, noop),
        migrations.RemoveIndex(
            model_name="productmaterial",
            name="products_pr_change__267b26_idx",
        ),
        migrations.RenameField(
            model_name="productmaterial",
            old_name="material_type",
            new_name="material_type_code",
        ),
        migrations.AlterField(
            model_name="productmaterial",
            name="material_type_code",
            field=models.CharField(max_length=64),
        ),
        migrations.AddIndex(
            model_name="productmaterial",
            index=models.Index(
                fields=["change_set", "material_type_code"],
                name="products_pr_change__e37bb1_idx",
            ),
        ),
        migrations.RemoveField(
            model_name="productmaterial",
            name="confirmation",
        ),
        migrations.CreateModel(
            name="MaterialConfirmation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "public_id",
                    models.UUIDField(
                        db_index=True, default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("content_hash", models.CharField(max_length=64)),
                ("requested_at", models.DateTimeField()),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("APPROVED", "Approved"),
                            ("RETURNED", "Returned"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("comment", models.TextField(blank=True, default="")),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("live_slot", models.PositiveSmallIntegerField(blank=True, default=1, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "confirmer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="material_confirmations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="material_confirmations",
                        to="documents.documentversion",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="confirmations",
                        to="products.productmaterial",
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
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requested_material_confirmations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "products_material_confirmation",
                "indexes": [
                    models.Index(fields=["material", "decision"], name="products_ma_materia_397e72_idx"),
                    models.Index(
                        fields=["document_version", "superseded_at"],
                        name="products_ma_documen_a1a5fa_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("material", "live_slot"),
                        name="products_material_live_confirmation_uniq",
                    )
                ],
            },
        ),
    ]
