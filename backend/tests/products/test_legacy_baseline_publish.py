"""Legacy baseline publication tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.platform.application.command import CommandContext
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductSourceType,
)
from apps.products.services.import_batch import ConfirmProductImportBatch
from apps.products.services.import_template import sample_import_csv
from apps.products.services.import_batch import CreateProductImportBatch
from apps.products.services.publish_legacy_baseline import PublishLegacyBaseline


@pytest.fixture
def baseline_director(product_director, grant_action: Callable[..., None]):
    grant_action(product_director, "migration.upload", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "migration.confirm", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(
        product_director,
        "product.publish_baseline",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    return product_director


@pytest.fixture
def confirmed_legacy_baseline(organization, baseline_director):
    del organization
    batch = CreateProductImportBatch(
        context=CommandContext.for_actor(baseline_director),
        csv_content=sample_import_csv(),
    ).execute()
    ConfirmProductImportBatch(
        context=CommandContext.for_actor(baseline_director),
        batch_public_id=batch.public_id,
        idempotency_key="confirm-baseline",
    ).execute()
    item = batch.items.filter(baseline_change_set__isnull=False).first()
    assert item is not None
    return item.baseline_change_set


@pytest.mark.django_db(transaction=True)
def test_publish_legacy_baseline_activates_product(
    confirmed_legacy_baseline: ProductChangeSet,
    baseline_director,
) -> None:
    result = PublishLegacyBaseline(
        context=CommandContext.for_actor(baseline_director),
        baseline_public_id=confirmed_legacy_baseline.public_id,
        idempotency_key="publish-legacy-1",
    ).execute()
    product = ProductAsset.objects.get(pk=confirmed_legacy_baseline.product_id)
    assert product.lifecycle_status == ProductLifecycleStatus.ACTIVE
    assert product.primary_version_id == result.product_version.id
    confirmed_legacy_baseline.refresh_from_db()
    assert confirmed_legacy_baseline.status == ChangeSetStatus.PUBLISHED


@pytest.mark.django_db(transaction=True)
def test_publish_legacy_baseline_is_idempotent(
    confirmed_legacy_baseline: ProductChangeSet,
    baseline_director,
) -> None:
    first = PublishLegacyBaseline(
        context=CommandContext.for_actor(baseline_director),
        baseline_public_id=confirmed_legacy_baseline.public_id,
        idempotency_key="publish-legacy-1",
    ).execute()
    second = PublishLegacyBaseline(
        context=CommandContext.for_actor(baseline_director),
        baseline_public_id=confirmed_legacy_baseline.public_id,
        idempotency_key="publish-legacy-1",
    ).execute()
    assert first.product_version.public_id == second.product_version.public_id
    assert (
        ProductChangeSet.objects.filter(
            change_type=ChangeSetType.LEGACY_BASELINE,
            status=ChangeSetStatus.PUBLISHED,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_legacy_import_product_has_legacy_source_type(
    confirmed_legacy_baseline: ProductChangeSet,
) -> None:
    product = confirmed_legacy_baseline.product
    assert product.source_type == ProductSourceType.LEGACY_IMPORT
