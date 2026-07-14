"""External binding uniqueness, authorization, and conflict rules."""

from __future__ import annotations

import pytest

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import ExternalBinding
from apps.integrations.services.external_binding import ExternalBindingInput, UpsertExternalBinding
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.errors import ExternalBindingConflict
from apps.products.models import ProductAsset, ProductLifecycleStatus, ProductSourceType


@pytest.mark.django_db
def test_external_binding_rejects_duplicate_active_identifier(
    organization: Organization,
    product_asset: ProductAsset,
    product_manager: User,
) -> None:
    other = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-OTHER",
        name="Other yogurt",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.DEVELOPING,
        product_owner=product_manager,
    )
    UpsertExternalBinding(
        context=CommandContext.for_actor(product_manager),
        product_public_id=product_asset.public_id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-001",
            internal_object_type="product",
            internal_object_id=product_asset.id,
        ),
    ).execute()

    with pytest.raises(ExternalBindingConflict):
        UpsertExternalBinding(
            context=CommandContext.for_actor(product_manager),
            product_public_id=other.public_id,
            binding=ExternalBindingInput(
                source_system="ERP",
                object_type="PRODUCT",
                external_id="EXT-001",
                internal_object_type="product",
                internal_object_id=other.id,
            ),
        ).execute()


@pytest.mark.django_db
def test_external_binding_allows_same_internal_object_rebind(
    product_asset: ProductAsset,
    product_manager: User,
) -> None:
    UpsertExternalBinding(
        context=CommandContext.for_actor(product_manager),
        product_public_id=product_asset.public_id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-002",
            internal_object_type="product",
            internal_object_id=product_asset.id,
        ),
    ).execute()
    row = UpsertExternalBinding(
        context=CommandContext.for_actor(product_manager),
        product_public_id=product_asset.public_id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-002",
            internal_object_type="product",
            internal_object_id=product_asset.id,
        ),
    ).execute()
    assert (
        ExternalBinding.objects.filter(
            source_system="ERP",
            external_id="EXT-002",
        ).count()
        == 1
    )
    assert row.internal_object_id == product_asset.id


@pytest.mark.django_db
def test_external_binding_requires_manage_permission(
    product_asset: ProductAsset,
    ordinary_employee: User,
) -> None:
    with pytest.raises(PermissionDeniedError):
        UpsertExternalBinding(
            context=CommandContext.for_actor(ordinary_employee),
            product_public_id=product_asset.public_id,
            binding=ExternalBindingInput(
                source_system="ERP",
                object_type="PRODUCT",
                external_id="EXT-003",
                internal_object_type="product",
                internal_object_id=product_asset.id,
            ),
        ).execute()
