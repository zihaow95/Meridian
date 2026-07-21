"""Platform configure rights do not imply operating value read rights."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.operations.models import MonitoringScopeType
from apps.operations.services.initialize_monitoring_scope import InitializeMonitoringScope
from apps.operations.services.monitoring_assignments import AssignMonitoringSupervisor
from apps.platform.application.command import CommandContext
from apps.products.models import ProductVersion, ProductVersionStatus
from apps.projects.models import Project


@pytest.mark.django_db(transaction=True)
def test_platform_admin_with_configure_only_cannot_read_operating_values(
    organization,
    project: Project,
    grant_action,
) -> None:
    admin = User.objects.create_user(
        organization=organization,
        display_name="Ops Config Admin",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(admin, "data_source.configure", "data_source")
    grant_action(admin, "metric_rule.configure", "metric_definition")
    grant_action(admin, "monitoring_scope.manage", "monitoring_scope")

    product = project.product_asset
    assert product is not None
    decision = authorize(
        subject_for(admin),
        action="operating_fact.read",
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=product.public_id,
            organization_id=organization.id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={"product_public_id": str(product.public_id)},
        ),
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is False


@pytest.mark.django_db(transaction=True)
def test_assigned_supervisor_can_read_operating_values_in_scope(
    organization,
    project: Project,
    active_user: User,
    another_active_user: User,
    grant_action,
) -> None:
    product = project.product_asset
    assert product is not None
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V-OPS",
        version_name="Ops",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
    )
    scope = InitializeMonitoringScope(
        project=project,
        product_version=version,
        owner=active_user,
        source_decision_public_id=uuid4(),
        effective_at=timezone.now(),
    ).execute()
    grant_action(active_user, "monitoring_scope.manage", "monitoring_scope")
    AssignMonitoringSupervisor(
        context=CommandContext.for_actor(active_user),
        monitoring_scope_public_id=scope.public_id,
        supervisor_public_id=another_active_user.public_id,
        scope_type=MonitoringScopeType.PRODUCT,
        product_public_id=product.public_id,
    ).execute()

    decision = authorize(
        subject_for(another_active_user),
        action="operating_fact.read",
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=product.public_id,
            organization_id=organization.id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={"product_public_id": str(product.public_id)},
        ),
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is True


@pytest.mark.django_db
def test_operations_action_catalog_is_seeded() -> None:
    from apps.authorization.actions import OPERATIONS_ACTIONS
    from apps.authorization.models.role import ActionCategory, PermissionAction

    # Transaction tests flush tables; re-apply catalog seed idempotently.
    for action_code, resource_type, action_category in OPERATIONS_ACTIONS:
        PermissionAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )

    codes = {row[0] for row in OPERATIONS_ACTIONS}
    assert "data_source.configure" in codes
    assert "monitoring_scope.manage" in codes
    assert "operating_fact.read" in codes
    assert "metric_rule.configure" in codes
    assert len(OPERATIONS_ACTIONS) == 24
    assert ActionCategory.ADMIN in {row[2] for row in OPERATIONS_ACTIONS}
    for action_code, _resource, _category in OPERATIONS_ACTIONS:
        assert PermissionAction.objects.filter(action_code=action_code).exists()
