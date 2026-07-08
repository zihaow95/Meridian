"""Platform action catalog seeding."""

from __future__ import annotations

import pytest

from apps.authorization.models.role import PermissionAction


@pytest.mark.django_db
def test_platform_action_catalog_is_seeded_after_migration() -> None:
    assert PermissionAction.objects.filter(action_code="audit.event.read").exists()
    assert PermissionAction.objects.filter(action_code="notification.todo.read").exists()
