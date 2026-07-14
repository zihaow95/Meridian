"""Seed product_change_set.approve action added after phase 3 review."""

from __future__ import annotations

from django.db import migrations


def seed_approve_action(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    permission_action.objects.get_or_create(
        action_code="product_change_set.approve",
        defaults={
            "resource_type": "product_change_set",
            "action_category": "DECIDE",
            "description": "",
        },
    )


def unseed_approve_action(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    permission_action.objects.filter(action_code="product_change_set.approve").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0005_seed_product_actions"),
    ]

    operations = [
        migrations.RunPython(seed_approve_action, unseed_approve_action),
    ]
