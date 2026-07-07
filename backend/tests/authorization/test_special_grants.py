"""Special grant authorization rules."""

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
    Role,
    RolePermission,
    RoleType,
)
from apps.authorization.policies.engine import authorize
from apps.authorization.services.create_special_grant import (
    CreateSpecialGrant,
    GrantExceedsGrantorScope,
)
from apps.platform.application.command import CommandContext


@pytest.mark.django_db
def test_grantor_without_permission_cannot_create_special_grant(
    active_user, another_active_user
) -> None:
    context = CommandContext.for_actor(active_user)
    with pytest.raises(GrantExceedsGrantorScope):
        CreateSpecialGrant(
            context=context,
            grantee=another_active_user,
            resource_type="product.formula",
            resource_public_id=uuid4(),
            actions=["product.formula.read"],
            max_sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
            purpose="investigation",
        ).execute()


@pytest.mark.django_db
def test_special_grant_allows_grantee_to_read_resource(
    organization,
    active_user,
    another_active_user,
) -> None:
    action = PermissionAction.objects.create(
        action_code="product.formula.read",
        resource_type="product.formula",
        action_category=ActionCategory.READ,
    )
    role = Role.objects.create(
        role_code="PRODUCT_MANAGER",
        name="Product Manager",
        role_type=RoleType.BUSINESS,
    )
    RolePermission.objects.create(
        role=role,
        action=action,
        max_data_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
        requires_object_scope=False,
    )
    from django.utils import timezone

    from apps.authorization.models.assignment import RoleAssignment, ScopeType

    RoleAssignment.objects.create(
        user=active_user,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        effective_from=timezone.now(),
        configured_by=active_user,
    )

    resource_id = uuid4()
    CreateSpecialGrant(
        context=CommandContext.for_actor(active_user),
        grantee=another_active_user,
        resource_type="product.formula",
        resource_public_id=resource_id,
        actions=["product.formula.read"],
        max_sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
        purpose="investigation",
    ).execute()

    decision = authorize(
        AuthorizationSubject(user=another_active_user, role_codes=frozenset()),
        action="product.formula.read",
        resource=ResourceDescriptor(
            resource_type="product.formula",
            public_id=resource_id,
            organization_id=organization.id,
            sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
        ),
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is True
