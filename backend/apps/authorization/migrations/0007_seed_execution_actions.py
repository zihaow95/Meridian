"""Seed phase 4 project execution permission actions."""

from __future__ import annotations

from django.db import migrations

from apps.authorization.actions import EXECUTION_ACTIONS


def seed_execution_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    for action_code, resource_type, action_category in EXECUTION_ACTIONS:
        permission_action.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )


def unseed_execution_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    action_codes = [row[0] for row in EXECUTION_ACTIONS]
    permission_action.objects.filter(action_code__in=action_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0006_seed_change_set_approve_action"),
    ]

    operations = [
        migrations.RunPython(seed_execution_actions, unseed_execution_actions),
    ]
