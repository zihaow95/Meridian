"""Product version, SKU, and channel configuration relationships."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.platform.application.command import CommandContext
from apps.products.models import (
    SKU,
    ChangeSetStatus,
    ChangeSetType,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductVersion,
    ProductVersionStatus,
)
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject


@pytest.fixture
def channel_dict() -> dict[str, str]:
    return {"KA": "Key account"}


@pytest.mark.django_db
def test_product_version_sku_and_channel_configuration_are_linked(
    product_asset: ProductAsset,
    channel_dict: dict[str, str],
) -> None:
    del channel_dict
    version = ProductVersion.objects.create(
        organization=product_asset.organization,
        product=product_asset,
        version_code="V1",
        version_name="Initial version",
        status=ProductVersionStatus.DRAFT,
        definition_summary="Initial definition",
    )
    sku = SKU.objects.create(
        organization=product_asset.organization,
        product_version=version,
        sku_code="SKU-001",
        name="Single cup",
        specification="120g cup",
        net_content_value=Decimal("120.0000"),
        net_content_unit="g",
        sales_unit="cup",
    )
    channel = ChannelConfiguration.objects.create(
        organization=product_asset.organization,
        sku=sku,
        channel_code="KA",
        configuration_version=1,
        suggested_retail_price=Decimal("9.90"),
        channel_status=ChannelStatus.PLANNED,
    )
    assert channel.sku.product_version.product_id == product_asset.id


@pytest.mark.django_db
def test_project_creation_creates_new_product_change_set(approved_candidate, boss) -> None:
    result = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="phase3-change-set",
    ).execute()
    change_set = ProductChangeSet.objects.get(public_id=result.product_draft.public_id)
    assert change_set.change_type == ChangeSetType.NEW_PRODUCT
    assert change_set.status == ChangeSetStatus.DRAFT
    assert change_set.product.lifecycle_status == ProductLifecycleStatus.DEVELOPING
