"""Register OPERATING_SOURCE_MAPPING schema code in the configuration catalog.

Organization-scoped ConfigurationDefinition rows are created by
ConfigureOperatingDataSource when publishing a data source mapping.
"""

from __future__ import annotations

from django.db import migrations

from apps.configuration.schema_registry import OPERATING_SOURCE_MAPPING_CODE, get_schema


def assert_operating_source_mapping_schema(apps, schema_editor) -> None:
    del apps, schema_editor
    if get_schema(OPERATING_SOURCE_MAPPING_CODE) is None:
        raise RuntimeError(
            f"Missing schema registration for definition code: {OPERATING_SOURCE_MAPPING_CODE}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0002_seed_project_template_definition"),
    ]

    operations = [
        migrations.RunPython(assert_operating_source_mapping_schema, migrations.RunPython.noop),
    ]
