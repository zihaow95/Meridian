"""Duplicate detection for legacy product import rows."""

from __future__ import annotations

import pytest

from apps.products.models import ImportBatch, ImportBatchStatus, ImportItem, ImportItemStatus
from apps.products.services.duplicate_detection import DetectProductImportDuplicates


@pytest.fixture
def import_batch(organization, product_manager) -> ImportBatch:
    return ImportBatch.objects.create(
        organization=organization,
        template_version="legacy-product-v1",
        status=ImportBatchStatus.PARSED,
        created_by=product_manager,
    )


@pytest.fixture
def import_item(import_batch: ImportBatch) -> ImportItem:
    return ImportItem.objects.create(
        organization=import_batch.organization,
        batch=import_batch,
        row_number=1,
        raw_row_digest="digest",
        normalized_payload={"name": "Similar product", "category_code": "YOGURT"},
        item_status=ImportItemStatus.VALID,
    )


@pytest.fixture
def existing_sku(active_product):
    from apps.products.models import SKU

    version = active_product.primary_version
    return SKU.objects.create(
        organization=active_product.organization,
        product_version=version,
        sku_code="SKU-DUP",
        name="Cup",
        specification="120g",
        barcode="6901234567890",
    )


@pytest.mark.django_db
def test_exact_barcode_duplicate_requires_manual_review(
    import_item: ImportItem,
    existing_sku,
) -> None:
    import_item.normalized_payload = {
        "barcode": existing_sku.barcode,
        "name": "Similar product",
        "category_code": "YOGURT",
    }
    candidates = DetectProductImportDuplicates(item=import_item).execute()
    assert candidates[0].match_type == "BARCODE_EXACT"
    assert candidates[0].blocking is True
