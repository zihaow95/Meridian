"""Authorization engine default-deny rules."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import (
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.authorization.policies.engine import authorize


@pytest.mark.django_db
def test_platform_admin_cannot_read_highly_sensitive_business_resource(
    platform_admin_subject,
    highly_sensitive_resource,
    product_read_action: PermissionAction,
) -> None:
    decision = authorize(
        platform_admin_subject,
        action="product.formula.read",
        resource=highly_sensitive_resource,
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is False
    assert decision.reason_code == "NO_ALLOWING_POLICY"


@pytest.mark.django_db
def test_unknown_action_is_rejected(active_user, organization) -> None:
    subject = AuthorizationSubject(user=active_user, role_codes=frozenset())
    resource = ResourceDescriptor(
        resource_type="unknown",
        public_id=uuid4(),
        organization_id=organization.id,
    )
    decision = authorize(
        subject,
        action="unknown.action",
        resource=resource,
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is False
    assert decision.reason_code == "UNKNOWN_ACTION"


@pytest.mark.django_db
def test_business_role_can_read_when_permission_and_level_match(
    organization,
    active_user,
    product_read_action,
) -> None:
    role = Role.objects.create(
        role_code="PRODUCT_MANAGER",
        name="Product Manager",
        role_type=RoleType.BUSINESS,
    )
    RolePermission.objects.create(
        role=role,
        action=product_read_action,
        max_data_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
        requires_object_scope=False,
    )
    RoleAssignment.objects.create(
        user=active_user,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        effective_from=timezone.now(),
        configured_by=active_user,
    )
    subject = AuthorizationSubject(user=active_user, role_codes=frozenset({"PRODUCT_MANAGER"}))
    resource = ResourceDescriptor(
        resource_type="product.formula",
        public_id=uuid4(),
        organization_id=organization.id,
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
    )
    decision = authorize(
        subject,
        action="product.formula.read",
        resource=resource,
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is True
    assert decision.reason_code == "ALLOWED"
