"""Troubleshooting access rules."""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
)
from apps.authorization.policies.engine import authorize
from apps.authorization.services.open_troubleshoot_access import (
    OpenTroubleshootAccess,
    TroubleshootAccessDenied,
)
from apps.platform.application.command import CommandContext


@pytest.mark.django_db
def test_troubleshoot_access_allows_scoped_read(
    organization, active_user, platform_admin_user, grant_action
) -> None:
    resource_id = uuid4()
    PermissionAction.objects.get_or_create(
        action_code="platform.settings.read",
        defaults={
            "resource_type": "platform.settings",
            "action_category": ActionCategory.READ,
        },
    )
    grant_action(
        platform_admin_user,
        "authorization.troubleshoot.open",
        "authorization.troubleshoot_access",
    )
    OpenTroubleshootAccess(
        context=CommandContext.for_actor(platform_admin_user),
        user=active_user,
        resource_type="platform.settings",
        resource_public_id=resource_id,
        actions=["platform.settings.read"],
        max_sensitivity_level=DataSensitivityLevel.INTERNAL,
        purpose="incident response",
    ).execute()

    decision = authorize(
        AuthorizationSubject(user=active_user, role_codes=frozenset()),
        action="platform.settings.read",
        resource=ResourceDescriptor(
            resource_type="platform.settings",
            public_id=resource_id,
            organization_id=organization.id,
            sensitivity_level=DataSensitivityLevel.INTERNAL,
        ),
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is True


@pytest.mark.django_db
def test_user_without_permission_cannot_open_troubleshoot_access(
    active_user, another_active_user, organization
) -> None:
    with pytest.raises(TroubleshootAccessDenied):
        OpenTroubleshootAccess(
            context=CommandContext.for_actor(active_user),
            user=another_active_user,
            resource_type="platform.settings",
            resource_public_id=uuid4(),
            actions=["platform.settings.read"],
            max_sensitivity_level=DataSensitivityLevel.INTERNAL,
            purpose="incident response",
        ).execute()
