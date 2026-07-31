"""One writer for legacy baselines, whether a person or a spreadsheet asks.

The item-by-item form exists so a user can enter a single historical product
without building a spreadsheet. It must not become a second implementation of
"create the product and its baseline change set": the batch importer and the
form call the same service, so a rule fixed in one place holds in both.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import IntegrityError, transaction

from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    ImportItemDecision,
    ProductAsset,
    ProductChangeSet,
    ProductSourceType,
)
from apps.products.services.create_legacy_baseline import CreateLegacyBaselineDraft
from apps.products.services.import_batch import (
    ConfirmProductImportBatch,
    CreateProductImportBatch,
    DecideImportItem,
)

pytestmark = pytest.mark.django_db

FORM_PAYLOAD: dict[str, Any] = {
    "name": "老酸奶 200g",
    "category_code": "YOGURT",
    "brand_code": "MERIDIAN",
    "business_no": "LEG-FORM-0001",
    "specification": "200g/杯",
    "sku_code": "SKU-LEG-0001",
    "barcode": "6900000000001",
}

ONE_ROW_CSV = (
    "name,category_code,business_no,brand_code,sku_code,barcode,specification\n"
    "旧款酸奶,YOGURT,LEG-CSV-0001,BRAND-A,SKU-CSV-0001,6900000000002,150g/杯\n"
)


@pytest.fixture
def importer(active_user: User, grant_action) -> User:
    grant_action(active_user, "migration.upload", "migration")
    grant_action(active_user, "migration.confirm", "migration")
    grant_action(active_user, "migration.review", "migration")
    grant_action(active_user, "legacy_baseline.draft.create", "product_change_set")
    return active_user


def create_from_form(actor: User, **overrides: Any) -> Any:
    payload = {**FORM_PAYLOAD, **overrides.pop("payload", {})}
    return CreateLegacyBaselineDraft(
        context=CommandContext.for_actor(actor),
        payload=payload,
        idempotency_key=overrides.pop("idempotency_key", "form-1"),
        **overrides,
    ).execute()


def confirm_batch(actor: User) -> Any:
    batch = CreateProductImportBatch(
        context=CommandContext.for_actor(actor),
        csv_content=ONE_ROW_CSV,
        source_filename="legacy.csv",
    ).execute()
    return ConfirmProductImportBatch(
        context=CommandContext.for_actor(actor),
        batch_public_id=batch.public_id,
        idempotency_key="batch-1",
    ).execute()


def test_the_batch_importer_writes_its_baseline_through_the_shared_service(
    importer: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = CreateLegacyBaselineDraft.execute

    def spy(self: CreateLegacyBaselineDraft) -> Any:
        calls.append(self.idempotency_key)
        return original(self)

    monkeypatch.setattr(CreateLegacyBaselineDraft, "execute", spy)

    confirm_batch(importer)

    assert len(calls) == 1


def test_the_form_writes_its_baseline_through_the_same_service(
    importer: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = CreateLegacyBaselineDraft.execute

    def spy(self: CreateLegacyBaselineDraft) -> Any:
        calls.append(self.idempotency_key)
        return original(self)

    monkeypatch.setattr(CreateLegacyBaselineDraft, "execute", spy)

    create_from_form(importer)

    assert calls == ["form-1"]


def test_both_entry_points_produce_the_same_kind_of_change_set(importer: User) -> None:
    form_result = create_from_form(importer)
    confirm_batch(importer)

    batch_change_set = ProductChangeSet.objects.exclude(pk=form_result.change_set.pk).get()
    for change_set in (form_result.change_set, batch_change_set):
        assert change_set.change_type == ChangeSetType.LEGACY_BASELINE
        assert change_set.status == ChangeSetStatus.DRAFT
        assert "payload" in change_set.change_scope
        assert change_set.product.source_type == ProductSourceType.LEGACY_IMPORT
        assert change_set.created_by_id == importer.id


def test_the_form_records_the_entered_payload_on_the_draft(importer: User) -> None:
    result = create_from_form(importer)

    assert result.change_set.change_scope["payload"]["name"] == FORM_PAYLOAD["name"]
    assert result.change_set.change_scope["payload"]["sku_code"] == FORM_PAYLOAD["sku_code"]
    assert result.product.business_no == FORM_PAYLOAD["business_no"]
    assert result.product.product_owner_id == importer.id


def test_a_form_submission_replayed_with_the_same_key_returns_the_first_draft(
    importer: User,
) -> None:
    first = create_from_form(importer)
    second = create_from_form(importer)

    assert second.change_set.pk == first.change_set.pk
    assert second.created is False
    assert ProductAsset.objects.count() == 1


def test_a_second_submission_with_a_new_key_creates_a_separate_draft(
    importer: User,
) -> None:
    create_from_form(importer)

    second = create_from_form(
        importer,
        idempotency_key="form-2",
        payload={"business_no": "LEG-FORM-0002"},
    )

    assert second.created is True
    assert ProductAsset.objects.count() == 2


def test_database_refuses_a_repeated_draft_idempotency_key(importer: User, organization) -> None:
    first = create_from_form(importer)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductChangeSet.objects.create(
            organization=organization,
            change_type=ChangeSetType.LEGACY_BASELINE,
            status=ChangeSetStatus.DRAFT,
            product=first.product,
            title="duplicate key",
            created_by=importer,
            draft_idempotency_key=first.change_set.draft_idempotency_key,
        )


def test_a_form_submission_without_a_name_is_refused(importer: User) -> None:
    with pytest.raises(ValidationFailedError):
        create_from_form(importer, payload={"name": ""})

    assert ProductAsset.objects.count() == 0


def test_linking_to_an_existing_product_does_not_create_a_second_product(
    importer: User, product_asset: ProductAsset
) -> None:
    result = create_from_form(
        importer,
        existing_product=product_asset,
        payload={"business_no": product_asset.business_no},
    )

    assert result.product.pk == product_asset.pk
    assert result.change_set.change_scope["linked_existing_product"] is True
    assert ProductAsset.objects.count() == 1


def test_the_batch_path_keeps_recording_its_row_number(importer: User) -> None:
    confirm_batch(importer)

    change_set = ProductChangeSet.objects.get()
    assert change_set.change_scope["import_row_number"] == 1
    assert change_set.migration_batch_id is not None
    assert change_set.draft_idempotency_key is None


def test_a_batch_link_decision_still_reuses_the_shared_service(
    importer: User, product_asset: ProductAsset, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = CreateProductImportBatch(
        context=CommandContext.for_actor(importer),
        csv_content=ONE_ROW_CSV,
        source_filename="legacy.csv",
    ).execute()
    DecideImportItem(
        context=CommandContext.for_actor(importer),
        batch_public_id=batch.public_id,
        row_number=1,
        decision=ImportItemDecision.LINK,
        target_product_public_id=product_asset.public_id,
    ).execute()

    calls: list[Any] = []
    original = CreateLegacyBaselineDraft.execute

    def spy(self: CreateLegacyBaselineDraft) -> Any:
        calls.append(self.existing_product)
        return original(self)

    monkeypatch.setattr(CreateLegacyBaselineDraft, "execute", spy)

    ConfirmProductImportBatch(
        context=CommandContext.for_actor(importer),
        batch_public_id=batch.public_id,
        idempotency_key="batch-link",
    ).execute()

    assert calls == [product_asset]
    assert ProductAsset.objects.count() == 1
