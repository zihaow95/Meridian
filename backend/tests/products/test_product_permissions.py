"""Default-deny authorization for product object identities."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.utils import timezone

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.products.models import ProductAsset
from apps.projects.member_keys import active_member_key
from apps.projects.models import Project, ProjectMember, ProjectRole


def _resource(
    product: ProductAsset,
    *,
    sensitivity: str = DataSensitivityLevel.INTERNAL,
) -> ResourceDescriptor:
    return ResourceDescriptor(
        resource_type="product",
        public_id=product.public_id,
        organization_id=product.organization_id,
        sensitivity_level=sensitivity,
    )


def _authorize(user: User, action: str, resource: ResourceDescriptor) -> bool:
    return authorize(
        subject_for(user),
        action=action,
        resource=resource,
        context=AuthorizationContext.current(),
    ).allowed


@pytest.fixture
def product_asset(
    organization: Organization,
    product_manager: User,
) -> ProductAsset:
    from apps.products.models import ProductLifecycleStatus, ProductSourceType

    return ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-PERM",
        name="Permission yogurt",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.DEVELOPING,
        product_owner=product_manager,
    )


@pytest.mark.django_db
def test_unrelated_user_is_denied_product_read_basic(
    product_asset: ProductAsset,
    another_active_user: User,
) -> None:
    assert not _authorize(
        another_active_user,
        "product.read_basic",
        _resource(product_asset),
    )


@pytest.mark.django_db
def test_product_owner_reads_sensitive_fields(
    product_asset: ProductAsset,
    product_manager: User,
) -> None:
    resource = _resource(product_asset, sensitivity=DataSensitivityLevel.SENSITIVE_CONTROLLED)
    assert _authorize(product_manager, "product.read_sensitive", resource)
    assert _authorize(product_manager, "product_draft.edit_group", resource)


@pytest.mark.django_db
def test_project_leader_reads_sensitive_but_cannot_export(
    project: Project,
    product_manager: User,
    another_active_user: User,
) -> None:
    product_asset = project.product_asset
    assert product_asset is not None
    assert project.leader_id == product_manager.id

    product_asset.product_owner = another_active_user
    product_asset.save(update_fields=["product_owner", "updated_at"])

    resource = _resource(product_asset, sensitivity=DataSensitivityLevel.SENSITIVE_CONTROLLED)
    assert _authorize(product_manager, "product.read_sensitive", resource)
    assert not _authorize(product_manager, "product.export", resource)


@pytest.mark.django_db
def test_project_member_reads_basic_only(
    project: Project,
    another_active_user: User,
    active_user: User,
) -> None:
    product_asset = project.product_asset
    assert product_asset is not None

    now = timezone.now()
    ProjectMember.objects.create(
        organization=project.organization,
        project=project,
        user=another_active_user,
        project_role=ProjectRole.MEMBER,
        active_from=now,
        active_role_key=active_member_key(project.id, another_active_user.id, ProjectRole.MEMBER),
        appointed_by=active_user,
    )

    resource = _resource(product_asset, sensitivity=DataSensitivityLevel.SENSITIVE_CONTROLLED)
    assert _authorize(another_active_user, "product.read_basic", resource)
    assert not _authorize(another_active_user, "product.read_sensitive", resource)


@pytest.mark.django_db
def test_platform_admin_cannot_read_highly_sensitive_product_values(
    product_asset: ProductAsset,
    platform_admin_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(platform_admin_user, "product.read_sensitive", "product", role_code="SYSTEM_ADMIN")
    resource = _resource(product_asset, sensitivity=DataSensitivityLevel.HIGHLY_SENSITIVE)
    assert not _authorize(platform_admin_user, "product.read_sensitive", resource)


@pytest.mark.django_db
def test_product_director_can_publish_baseline_with_rbac_grant(
    product_asset: ProductAsset,
    grant_action: Callable[..., None],
    another_active_user: User,
) -> None:
    grant_action(
        another_active_user,
        "product.publish_baseline",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    assert _authorize(another_active_user, "product.publish_baseline", _resource(product_asset))
