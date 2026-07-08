"""Seed phase 1 platform permission actions."""

from __future__ import annotations

from django.db import migrations

from apps.authorization.actions import PLATFORM_ACTIONS


def seed_platform_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    for action_code, resource_type, action_category in PLATFORM_ACTIONS:
        permission_action.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )


def unseed_platform_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    action_codes = [row[0] for row in PLATFORM_ACTIONS]
    permission_action.objects.filter(action_code__in=action_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0002_securitysetting_adminchangerequest_specialgrant_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_platform_actions, unseed_platform_actions),
    ]
