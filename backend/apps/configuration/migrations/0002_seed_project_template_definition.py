"""Register that PROJECT_EXECUTION_TEMPLATE V1 defaults ship with the codebase.

Organization-scoped ConfigurationDefinition rows are created when an admin
imports/publishes the JSON under apps/configuration/defaults/project_template_v1.json.
This migration only asserts the seed artifact is present.
"""

from __future__ import annotations

from pathlib import Path

from django.db import migrations


def assert_template_seed_present(apps, schema_editor) -> None:
    seed = Path(__file__).resolve().parents[1] / "defaults" / "project_template_v1.json"
    if not seed.is_file():
        raise RuntimeError(f"Missing project template seed: {seed}")


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(assert_template_seed_present, migrations.RunPython.noop),
    ]
