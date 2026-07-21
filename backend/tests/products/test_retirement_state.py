"""products.ApplyApprovedRetirementAction owns product/SKU/channel mutations."""

from __future__ import annotations

from datetime import date

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.products.models import (
    SKU,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductionStatus,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)
from apps.products.services.retirement import ApplyApprovedRetirementAction


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RET-STATE",
        name="State yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-RET-STATE",
        name="Cup",
        specification="120g",
        status=SKUStatus.ACTIVE,
        production_status=ProductionStatus.IN_PRODUCTION,
    )
    channel = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    return {"product": product, "version": version, "sku": sku, "channel": channel}


@pytest.mark.django_db(transaction=True)
def test_apply_actions_mutate_only_scoped_fields(catalog, active_user, grant_action) -> None:
    grant_action(active_user, "retirement_plan.execute", "retirement_plan")
    scope = {
        "product_version_public_ids": [str(catalog["version"].public_id)],
        "sku_public_ids": [str(catalog["sku"].public_id)],
        "channel_public_ids": [str(catalog["channel"].public_id)],
    }
    ctx = CommandContext.for_actor(active_user)
    ApplyApprovedRetirementAction(
        context=ctx,
        action_type="STOP_PRODUCTION",
        product_public_id=catalog["product"].public_id,
        scope_snapshot=scope,
        as_of=date(2026, 1, 1),
    ).execute()
    catalog["sku"].refresh_from_db()
    assert catalog["sku"].production_status == ProductionStatus.STOPPED
    assert catalog["sku"].status == SKUStatus.ACTIVE

    ApplyApprovedRetirementAction(
        context=ctx,
        action_type="STOP_SALE",
        product_public_id=catalog["product"].public_id,
        scope_snapshot=scope,
        as_of=date(2026, 2, 1),
    ).execute()
    catalog["channel"].refresh_from_db()
    assert catalog["channel"].channel_status == ChannelStatus.OFF_SALE

    ApplyApprovedRetirementAction(
        context=ctx,
        action_type="RETIRE",
        product_public_id=catalog["product"].public_id,
        scope_snapshot=scope,
        as_of=date(2026, 3, 1),
    ).execute()
    catalog["sku"].refresh_from_db()
    catalog["version"].refresh_from_db()
    catalog["product"].refresh_from_db()
    assert catalog["sku"].status == SKUStatus.INACTIVE
    assert catalog["version"].status == ProductVersionStatus.INACTIVE
    assert catalog["product"].lifecycle_status == ProductLifecycleStatus.RETIRED
    assert catalog["product"].retired_at is not None
