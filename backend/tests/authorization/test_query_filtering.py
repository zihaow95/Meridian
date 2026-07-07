"""Database-layer visibility filtering."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.authorization.queries.visible_resources import VisibleResourceFilter


@pytest.mark.django_db
def test_visible_filter_denies_without_matching_assignment(organization, active_user) -> None:
    PermissionAction.objects.create(
        action_code="sample.read",
        resource_type="sample",
        action_category=ActionCategory.READ,
    )
    resource_filter = VisibleResourceFilter(
        user=active_user,
        action="sample.read",
        organization_id=organization.id,
    )
    condition = resource_filter.build_queryset_filter(model=object, resource_type="sample")
    assert "pk__in" in str(condition)


@pytest.mark.django_db
def test_visible_filter_allows_organization_scope(organization, active_user) -> None:
    action = PermissionAction.objects.create(
        action_code="sample.read",
        resource_type="sample",
        action_category=ActionCategory.READ,
    )
    role = Role.objects.create(
        role_code="SAMPLE_READER",
        name="Sample Reader",
        role_type=RoleType.BUSINESS,
    )
    RolePermission.objects.create(
        role=role,
        action=action,
        max_data_level=DataSensitivityLevel.INTERNAL,
        requires_object_scope=False,
    )
    RoleAssignment.objects.create(
        user=active_user,
        role=role,
        scope_type=ScopeType.ORGANIZATION,
        effective_from=timezone.now(),
        configured_by=active_user,
    )
    resource_filter = VisibleResourceFilter(
        user=active_user,
        action="sample.read",
        organization_id=organization.id,
    )
    projected = resource_filter.project_fields(
        {"name": "Widget", "formula_detail": "secret"},
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
    )
    assert "formula_detail" not in projected
    assert projected["name"] == "Widget"
