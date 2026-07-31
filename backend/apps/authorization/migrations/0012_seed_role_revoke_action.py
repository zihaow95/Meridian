"""Seed authorization.role.revoke action."""

from __future__ import annotations

from django.db import migrations


def seed_role_revoke_action(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    permission_action.objects.get_or_create(
        action_code="authorization.role.revoke",
        defaults={
            "resource_type": "authorization.role",
            "action_category": "ADMIN",
            "description": "Revoke / deactivate an active role assignment",
        },
    )


def unseed_role_revoke_action(apps, schema_editor) -> None:
    permission_action = apps.get_model("authorization", "PermissionAction")
    permission_action.objects.filter(action_code="authorization.role.revoke").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0011_role_assignment_scope_key"),
    ]

    operations = [
        migrations.RunPython(seed_role_revoke_action, unseed_role_revoke_action),
    ]
