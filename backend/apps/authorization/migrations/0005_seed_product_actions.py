"""Seed phase 3 product permission actions."""

from __future__ import annotations

from django.db import migrations

from apps.authorization.actions import PRODUCT_ACTIONS


def seed_product_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    for action_code, resource_type, action_category in PRODUCT_ACTIONS:
        permission_action.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )


def unseed_product_actions(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    action_codes = [row[0] for row in PRODUCT_ACTIONS]
    permission_action.objects.filter(action_code__in=action_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0004_seed_opportunity_actions"),
    ]

    operations = [
        migrations.RunPython(seed_product_actions, unseed_product_actions),
    ]

