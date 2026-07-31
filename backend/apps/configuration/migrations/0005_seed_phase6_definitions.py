"""Register the four phase 6 definition codes in the configuration catalog.

Organization-scoped ConfigurationDefinition rows are created when an
administrator drafts the first version, so this migration only guarantees the
code-registered schemas exist before any draft can reference them.
"""

from __future__ import annotations

from django.db import migrations

from apps.configuration.schema_registry import (
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    TECHNICAL_FILE_CATALOG_CODE,
    get_schema,
)

PHASE6_DEFINITION_CODES = (
    TECHNICAL_FILE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    NOTIFICATION_DELIVERY_POLICY_CODE,
)


def assert_phase6_schemas(apps, schema_editor) -> None:
    del apps, schema_editor
    missing = [code for code in PHASE6_DEFINITION_CODES if get_schema(code) is None]
    if missing:
        raise RuntimeError(f"Missing schema registration for definition codes: {missing}")


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0004_current_published_slot"),
    ]

    operations = [
        migrations.RunPython(assert_phase6_schemas, migrations.RunPython.noop),
    ]
