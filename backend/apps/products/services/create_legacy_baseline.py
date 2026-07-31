"""The single writer for a legacy baseline draft.

Both the item-by-item form and the spreadsheet importer end here. What differs
between them — who authorizes, which row, which batch — stays with the caller;
creating the product asset and its baseline change set happens only here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    CompletenessStatus,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductSourceType,
)

REQUIRED_PAYLOAD_FIELDS = ("name", "category_code")


@dataclass(frozen=True)
class LegacyBaselineDraft:
    product: ProductAsset
    change_set: ProductChangeSet
    created: bool


def find_draft_by_idempotency_key(
    *, organization_id: int, idempotency_key: str
) -> ProductChangeSet | None:
    return (
        ProductChangeSet.objects.select_related("product")
        .filter(organization_id=organization_id, draft_idempotency_key=idempotency_key)
        .first()
    )


@dataclass
class CreateLegacyBaselineDraft:
    context: CommandContext
    payload: dict[str, Any]
    # None for the batch importer: a spreadsheet row is already deduplicated by
    # the batch itself, so it does not need a second key.
    idempotency_key: str | None = None
    existing_product: ProductAsset | None = None
    migration_batch_id: int | None = None
    import_row_number: int | None = None
    business_no_fallback: str = ""
    extra_scope: dict[str, Any] = field(default_factory=dict)

    def execute(self) -> LegacyBaselineDraft:
        actor = self.context.actor
        missing = [
            name
            for name in REQUIRED_PAYLOAD_FIELDS
            if not str(self.payload.get(name) or "").strip()
        ]
        if missing:
            raise ValidationFailedError(
                message="The legacy baseline needs these fields: " + ", ".join(missing),
                details={"blocks": ["PRODUCT_REQUIRED_FIELD_MISSING"], "fields": missing},
            )

        with transaction.atomic():
            if self.idempotency_key:
                replay = find_draft_by_idempotency_key(
                    organization_id=actor.organization_id,
                    idempotency_key=self.idempotency_key,
                )
                if replay is not None:
                    return LegacyBaselineDraft(
                        product=replay.product, change_set=replay, created=False
                    )

            product = self.existing_product or self._create_product(actor)
            change_set = ProductChangeSet.objects.create(
                organization_id=actor.organization_id,
                change_type=ChangeSetType.LEGACY_BASELINE,
                status=ChangeSetStatus.DRAFT,
                product=product,
                migration_batch_id=self.migration_batch_id,
                title=self._title(product),
                definition_summary=str(self.payload.get("specification") or ""),
                completeness_status=self._completeness(),
                change_scope=self._scope(),
                created_by=actor,
                draft_idempotency_key=self.idempotency_key or None,
            )

        return LegacyBaselineDraft(product=product, change_set=change_set, created=True)

    def _create_product(self, actor: Any) -> ProductAsset:
        business_no = str(self.payload.get("business_no") or self.business_no_fallback)
        return ProductAsset.objects.create(
            organization_id=actor.organization_id,
            business_no=business_no,
            name=str(self.payload["name"]),
            brand_code=str(self.payload.get("brand_code") or ""),
            category_code=str(self.payload["category_code"]),
            source_type=ProductSourceType.LEGACY_IMPORT,
            lifecycle_status=ProductLifecycleStatus.DEVELOPING,
            product_owner=actor,
        )

    def _title(self, product: ProductAsset) -> str:
        if self.existing_product is not None:
            return f"Legacy baseline link: {product.name}"
        return f"Legacy baseline: {product.name}"

    def _completeness(self) -> str:
        if self.existing_product is not None:
            return CompletenessStatus.PARTIAL
        complete = self.payload.get("sku_code") and self.payload.get("barcode")
        return CompletenessStatus.COMPLETE if complete else CompletenessStatus.PARTIAL

    def _scope(self) -> dict[str, Any]:
        scope: dict[str, Any] = {"payload": self.payload}
        if self.import_row_number is not None:
            scope["import_row_number"] = self.import_row_number
        if self.existing_product is not None:
            scope["linked_existing_product"] = True
        scope.update(self.extra_scope)
        return scope
