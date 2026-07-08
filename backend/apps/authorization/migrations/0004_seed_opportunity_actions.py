"""Seed phase 2 opportunity permission actions."""

from __future__ import annotations

from django.db import migrations

from apps.authorization.actions import OPPORTUNITY_ACTIONS


def seed_opportunity_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    for action_code, resource_type, action_category in OPPORTUNITY_ACTIONS:
        permission_action.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )


def unseed_opportunity_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    action_codes = [row[0] for row in OPPORTUNITY_ACTIONS]
    permission_action.objects.filter(action_code__in=action_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0003_seed_platform_actions"),
    ]

    operations = [
        migrations.RunPython(seed_opportunity_actions, unseed_opportunity_actions),
    ]
