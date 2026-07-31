"""Monitoring scope assignments: idempotent handover defaults and effective range."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    MonitoringScope,
    MonitoringScopeType,
)
from apps.operations.services.initialize_monitoring_scope import InitializeMonitoringScope
from apps.operations.services.monitoring_assignments import AssignMonitoringSupervisor
from apps.platform.application.command import CommandContext
from apps.products.models import ProductVersion, ProductVersionStatus
from apps.projects.models import Project


@pytest.fixture
def product_version(
    organization: Organization, active_user: User, project: Project
) -> ProductVersion:
    product = project.product_asset
    assert product is not None
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
    )
    return version


def _init_scope(
    *,
    project: Project,
    product_version: ProductVersion,
    owner: User,
    decision_id=None,
) -> MonitoringScope:
    return InitializeMonitoringScope(
        project=project,
        product_version=product_version,
        owner=owner,
        source_decision_public_id=decision_id or uuid4(),
        effective_at=timezone.now(),
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_handover_init_is_idempotent_with_one_default_product_assignment(
    project: Project,
    product_version: ProductVersion,
    active_user: User,
) -> None:
    decision_id = uuid4()
    first = _init_scope(
        project=project,
        product_version=product_version,
        owner=active_user,
        decision_id=decision_id,
    )
    second = _init_scope(
        project=project,
        product_version=product_version,
        owner=active_user,
        decision_id=decision_id,
    )

    assert first.public_id == second.public_id
    assert MonitoringScope.objects.filter(project=project).count() == 1
    assignments = MonitoringAssignment.objects.filter(monitoring_scope=first)
    assert assignments.count() == 1
    assignment = assignments.get()
    assert assignment.scope_type == MonitoringScopeType.PRODUCT
    assert assignment.supervisor_id == active_user.id
    assert assignment.product_id == product_version.product_id
    assert assignment.sku_id is None
    assert assignment.channel_id is None
    assert assignment.status == MonitoringAssignmentStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_same_supervisor_and_scope_has_one_active_assignment(
    project: Project,
    product_version: ProductVersion,
    active_user: User,
    another_active_user: User,
    grant_action,
) -> None:
    scope = _init_scope(project=project, product_version=product_version, owner=active_user)
    grant_action(active_user, "monitoring_scope.manage", "monitoring_scope")
    product = product_version.product

    first = AssignMonitoringSupervisor(
        context=CommandContext.for_actor(active_user),
        monitoring_scope_public_id=scope.public_id,
        supervisor_public_id=another_active_user.public_id,
        scope_type=MonitoringScopeType.PRODUCT,
        product_public_id=product.public_id,
    ).execute()
    second = AssignMonitoringSupervisor(
        context=CommandContext.for_actor(active_user),
        monitoring_scope_public_id=scope.public_id,
        supervisor_public_id=another_active_user.public_id,
        scope_type=MonitoringScopeType.PRODUCT,
        product_public_id=product.public_id,
    ).execute()

    assert first.public_id == second.public_id
    active = MonitoringAssignment.objects.filter(
        monitoring_scope=scope,
        supervisor=another_active_user,
        scope_type=MonitoringScopeType.PRODUCT,
        product=product,
        status=MonitoringAssignmentStatus.ACTIVE,
    )
    assert active.count() == 1


@pytest.mark.django_db(transaction=True)
def test_expired_assignment_is_immediately_inactive(
    project: Project,
    product_version: ProductVersion,
    active_user: User,
    another_active_user: User,
    grant_action,
) -> None:
    scope = _init_scope(project=project, product_version=product_version, owner=active_user)
    grant_action(active_user, "monitoring_scope.manage", "monitoring_scope")
    now = timezone.now()

    assignment = AssignMonitoringSupervisor(
        context=CommandContext.for_actor(active_user),
        monitoring_scope_public_id=scope.public_id,
        supervisor_public_id=another_active_user.public_id,
        scope_type=MonitoringScopeType.PRODUCT,
        product_public_id=product_version.product.public_id,
        effective_from=now - timedelta(days=7),
        effective_to=now - timedelta(seconds=1),
    ).execute()

    assert assignment.is_effective(as_of=now) is False
    from apps.operations.policies.identity_provider import resolve_effective_assignments

    effective = resolve_effective_assignments(
        user=another_active_user,
        organization_id=project.organization_id,
        as_of=now,
    )
    assert all(row.public_id != assignment.public_id for row in effective)


@pytest.mark.django_db(transaction=True)
def test_active_slot_unique_constraint_enforced(
    project: Project,
    product_version: ProductVersion,
    active_user: User,
) -> None:
    scope = _init_scope(project=project, product_version=product_version, owner=active_user)
    existing = MonitoringAssignment.objects.get(monitoring_scope=scope)
    with pytest.raises(IntegrityError):
        MonitoringAssignment.objects.create(
            organization=scope.organization,
            monitoring_scope=scope,
            supervisor=active_user,
            product=product_version.product,
            scope_type=MonitoringScopeType.PRODUCT,
            scope_key=existing.scope_key,
            effective_from=timezone.now(),
            status=MonitoringAssignmentStatus.ACTIVE,
            active_slot=1,
            max_data_level=existing.max_data_level,
        )
