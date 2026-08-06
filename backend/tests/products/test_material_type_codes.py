"""Material types come from configuration, not from a frozen code enum."""

from __future__ import annotations

import importlib

import pytest
from django.db import migrations

from apps.products.models import ProductMaterial

governed_materials = importlib.import_module(
    "apps.products.migrations.0013_governed_product_materials"
)

pytestmark = pytest.mark.django_db


def test_the_legacy_enum_codes_survive_the_move_to_free_form_codes() -> None:
    """The old packaging/label codes must keep working after the rename."""

    assert governed_materials.KNOWN_LEGACY_MATERIAL_TYPES == frozenset(
        {
            "INNER_PACKAGING",
            "OUTER_PACKAGING",
            "LABEL",
            "DESIGN_SOURCE",
            "CHANNEL_IMAGE",
            "APPROVED_PRINT",
        }
    )


def test_a_material_can_be_stored_under_a_code_the_old_enum_never_had(
    organization, change_set, controlled_document_version
) -> None:
    material = ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type="PRODUCT",
        owner_id=change_set.product_id,
        material_type_code="REGULATORY_FILING",
        document_version=controlled_document_version(),
    )

    material.refresh_from_db()
    assert material.material_type_code == "REGULATORY_FILING"


def test_the_migration_stops_the_line_on_a_material_type_it_cannot_map() -> None:
    """An unmappable legacy value must halt the migration, not be dropped."""

    with pytest.raises(RuntimeError) as excinfo:
        governed_materials.assert_material_types_are_mappable(
            observed_types=["LABEL", "MYSTERY_TYPE"]
        )

    assert "MYSTERY_TYPE" in str(excinfo.value)


def test_the_migration_accepts_only_known_legacy_material_types() -> None:
    governed_materials.assert_material_types_are_mappable(
        observed_types=["LABEL", "INNER_PACKAGING"]
    )


def test_the_duplicate_guard_runs_before_the_migration_touches_the_schema() -> None:
    """MySQL cannot roll back applied DDL, so the stop-the-line check goes first."""

    operations = governed_materials.Migration.operations
    guard_index = next(
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.RunPython)
        and operation.code is governed_materials.reject_unmappable_material_types
    )
    first_schema_index = next(
        index
        for index, operation in enumerate(operations)
        if not isinstance(operation, migrations.RunPython)
    )

    assert guard_index < first_schema_index
