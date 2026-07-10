"""External binding uniqueness and conflict rules."""

from __future__ import annotations

import pytest

from apps.integrations.models import ExternalBinding
from apps.integrations.services.external_binding import ExternalBindingInput, UpsertExternalBinding
from apps.products.errors import ExternalBindingConflict


@pytest.mark.django_db
def test_external_binding_rejects_duplicate_active_identifier(organization, product_asset) -> None:
    UpsertExternalBinding(
        organization_id=organization.id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-001",
            internal_object_type="product_asset",
            internal_object_id=product_asset.id,
        ),
    ).execute()

    with pytest.raises(ExternalBindingConflict):
        UpsertExternalBinding(
            organization_id=organization.id,
            binding=ExternalBindingInput(
                source_system="ERP",
                object_type="PRODUCT",
                external_id="EXT-001",
                internal_object_type="product_asset",
                internal_object_id=product_asset.id + 999,
            ),
        ).execute()


@pytest.mark.django_db
def test_external_binding_allows_same_internal_object_rebind(organization, product_asset) -> None:
    UpsertExternalBinding(
        organization_id=organization.id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-002",
            internal_object_type="product_asset",
            internal_object_id=product_asset.id,
        ),
    ).execute()
    row = UpsertExternalBinding(
        organization_id=organization.id,
        binding=ExternalBindingInput(
            source_system="ERP",
            object_type="PRODUCT",
            external_id="EXT-002",
            internal_object_type="product_asset",
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
