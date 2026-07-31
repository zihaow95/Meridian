"""Seed phase 5 operations permission actions."""

from __future__ import annotations

from django.db import migrations

from apps.authorization.actions import OPERATIONS_ACTIONS


def seed_operations_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    for action_code, resource_type, action_category in OPERATIONS_ACTIONS:
        permission_action.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )


def unseed_operations_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    action_codes = [row[0] for row in OPERATIONS_ACTIONS]
    permission_action.objects.filter(action_code__in=action_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0007_seed_execution_actions"),
    ]

    operations = [
        migrations.RunPython(seed_operations_actions, unseed_operations_actions),
    ]
