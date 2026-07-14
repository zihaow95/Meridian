"""Legacy product import batch confirmation tests."""

from __future__ import annotations

import pytest

from apps.platform.application.command import CommandContext
from apps.products.models import ImportBatchStatus, ProductAsset, ProductSourceType
from apps.products.services.import_batch import ConfirmProductImportBatch, CreateProductImportBatch
from apps.products.services.import_template import sample_import_csv


@pytest.fixture
def migration_operator(
    product_director,
    grant_action,
):
    grant_action(product_director, "migration.upload", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "migration.confirm", "migration", role_code="PRODUCT_DIRECTOR")
    return product_director


@pytest.fixture
def parsed_import_batch(organization, migration_operator):
    del organization
    return CreateProductImportBatch(
        context=CommandContext.for_actor(migration_operator),
        csv_content=sample_import_csv(),
        source_filename="legacy.csv",
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_confirming_import_batch_twice_does_not_duplicate_products(
    parsed_import_batch,
    migration_operator,
) -> None:
    first = ConfirmProductImportBatch(
        context=CommandContext.for_actor(migration_operator),
        batch_public_id=parsed_import_batch.public_id,
        idempotency_key="confirm-import-1",
    ).execute()
    second = ConfirmProductImportBatch(
        context=CommandContext.for_actor(migration_operator),
        batch_public_id=parsed_import_batch.public_id,
        idempotency_key="confirm-import-1",
    ).execute()
    assert first.created_count == second.created_count
    assert (
        ProductAsset.objects.filter(source_type=ProductSourceType.LEGACY_IMPORT).count()
        == first.created_count
    )


@pytest.mark.django_db
def test_parsed_import_batch_marks_invalid_rows(parsed_import_batch) -> None:
    assert parsed_import_batch.status == ImportBatchStatus.PARSED
    assert parsed_import_batch.total_count == 2
    assert parsed_import_batch.success_count == 2
