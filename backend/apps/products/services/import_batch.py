"""Import batch parsing and confirmation services."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    CompletenessStatus,
    ImportBatch,
    ImportBatchStatus,
    ImportItem,
    ImportItemDecision,
    ImportItemStatus,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductSourceType,
)
from apps.products.services.duplicate_detection import (
    DetectProductImportDuplicates,
    serialize_candidates,
)
from apps.products.services.import_template import (
    IMPORT_TEMPLATE_VERSION,
    parse_import_csv,
)


@dataclass(frozen=True)
class ConfirmImportItemResult:
    row_number: int
    baseline_public_id: str | None
    item_status: str


@dataclass(frozen=True)
class ConfirmImportBatchResult:
    created_count: int
    linked_count: int
    skipped_count: int
    failed_count: int
    items: tuple[ConfirmImportItemResult, ...]


@dataclass
class CreateProductImportBatch:
    context: CommandContext
    csv_content: str
    source_filename: str = "import.csv"

    def execute(self) -> ImportBatch:
        actor = self.context.actor
        decision = authorize(
            subject_for(actor),
            action="migration.upload",
            resource=ResourceDescriptor(
                resource_type="migration",
                public_id=None,
                organization_id=actor.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

        digest = hashlib.sha256(self.csv_content.encode()).hexdigest()
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                organization_id=actor.organization_id,
                template_version=IMPORT_TEMPLATE_VERSION,
                status=ImportBatchStatus.PARSING,
                source_filename=self.source_filename,
                source_digest=digest,
                created_by=actor,
            )
            self._parse_rows(batch=batch, csv_content=self.csv_content)
        return batch

    def _parse_rows(self, *, batch: ImportBatch, csv_content: str) -> None:
        rows = parse_import_csv(content=csv_content)
        success_count = 0
        failure_count = 0
        for row in rows:
            item_status = (
                ImportItemStatus.INVALID if row.validation_errors else ImportItemStatus.VALID
            )
            if row.validation_errors:
                failure_count += 1
            else:
                success_count += 1
            item = ImportItem.objects.create(
                organization=batch.organization,
                batch=batch,
                row_number=row.row_number,
                raw_row_digest=row.raw_row_digest,
                normalized_payload=row.normalized_payload,
                validation_errors=row.validation_errors,
                item_status=item_status,
            )
            if item_status == ImportItemStatus.VALID:
                candidates = DetectProductImportDuplicates(item=item).execute()
                item.duplicate_candidates = serialize_candidates(candidates)
                if any(candidate["blocking"] for candidate in item.duplicate_candidates):
                    item.item_status = ImportItemStatus.DUPLICATE_REVIEW
                    item.decision = ImportItemDecision.PENDING
                item.save(
                    update_fields=[
                        "duplicate_candidates",
                        "item_status",
                        "decision",
                        "updated_at",
                    ]
                )

        batch.total_count = len(rows)
        batch.success_count = success_count
        batch.failure_count = failure_count
        batch.status = ImportBatchStatus.PARSED
        batch.save(
            update_fields=[
                "total_count",
                "success_count",
                "failure_count",
                "status",
                "updated_at",
            ]
        )


@dataclass
class ConfirmProductImportBatch:
    context: CommandContext
    batch_public_id: UUID
    idempotency_key: str

    def execute(self) -> ConfirmImportBatchResult:
        actor = self.context.actor
        decision = authorize(
            subject_for(actor),
            action="migration.confirm",
            resource=ResourceDescriptor(
                resource_type="migration",
                public_id=None,
                organization_id=actor.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

        with transaction.atomic():
            batch = (
                ImportBatch.objects.select_for_update()
                .filter(public_id=self.batch_public_id, organization_id=actor.organization_id)
                .first()
            )
            if batch is None:
                raise PermissionDeniedError()

            if (
                batch.confirm_idempotency_key == self.idempotency_key
                and batch.status == ImportBatchStatus.CONFIRMED
            ):
                return self._build_result(batch=batch)

            created_count = 0
            linked_count = 0
            skipped_count = 0
            failed_count = 0
            item_results: list[ConfirmImportItemResult] = []

            for item in batch.items.select_for_update().order_by("row_number"):
                result = self._confirm_item(batch=batch, item=item, actor=actor)
                item_results.append(result)
                if result.item_status == ImportItemStatus.CONFIRMED:
                    if item.decision == ImportItemDecision.LINK:
                        linked_count += 1
                    else:
                        created_count += 1
                elif result.item_status == ImportItemStatus.SKIPPED:
                    skipped_count += 1
                elif result.item_status == ImportItemStatus.FAILED:
                    failed_count += 1

            batch.created_count = created_count
            batch.linked_count = linked_count
            batch.skip_count = skipped_count
            batch.failure_count = failed_count
            batch.status = ImportBatchStatus.CONFIRMED
            batch.confirm_idempotency_key = self.idempotency_key
            batch.save(
                update_fields=[
                    "created_count",
                    "linked_count",
                    "skip_count",
                    "failure_count",
                    "status",
                    "confirm_idempotency_key",
                    "updated_at",
                ]
            )

        return ConfirmImportBatchResult(
            created_count=created_count,
            linked_count=linked_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            items=tuple(item_results),
        )

    def _build_result(self, *, batch: ImportBatch) -> ConfirmImportBatchResult:
        items = tuple(
            ConfirmImportItemResult(
                row_number=item.row_number,
                baseline_public_id=(
                    str(baseline.public_id)
                    if (baseline := item.baseline_change_set) is not None
                    else None
                ),
                item_status=item.item_status,
            )
            for item in batch.items.order_by("row_number")
        )
        return ConfirmImportBatchResult(
            created_count=batch.created_count,
            linked_count=batch.linked_count,
            skipped_count=batch.skip_count,
            failed_count=batch.failure_count,
            items=items,
        )

    def _confirm_item(
        self,
        *,
        batch: ImportBatch,
        item: ImportItem,
        actor: User,
    ) -> ConfirmImportItemResult:
        if item.baseline_change_set_id is not None:
            baseline = item.baseline_change_set
            assert baseline is not None
            return ConfirmImportItemResult(
                row_number=item.row_number,
                baseline_public_id=str(baseline.public_id),
                item_status=item.item_status,
            )

        if item.item_status == ImportItemStatus.INVALID:
            return ConfirmImportItemResult(
                row_number=item.row_number,
                baseline_public_id=None,
                item_status=item.item_status,
            )

        if item.decision == ImportItemDecision.SKIP:
            item.item_status = ImportItemStatus.SKIPPED
            item.save(update_fields=["item_status", "updated_at"])
            return ConfirmImportItemResult(
                row_number=item.row_number,
                baseline_public_id=None,
                item_status=item.item_status,
            )

        blocking = any(candidate.get("blocking") for candidate in item.duplicate_candidates)
        if item.item_status == ImportItemStatus.DUPLICATE_REVIEW and blocking:
            if item.decision not in {ImportItemDecision.CREATE, ImportItemDecision.LINK}:
                item.item_status = ImportItemStatus.FAILED
                item.error_code = "DUPLICATE_REQUIRES_DECISION"
                item.save(update_fields=["item_status", "error_code", "updated_at"])
                return ConfirmImportItemResult(
                    row_number=item.row_number,
                    baseline_public_id=None,
                    item_status=item.item_status,
                )

        if item.decision == ImportItemDecision.LINK:
            return self._link_existing_product(batch=batch, item=item, actor=actor)

        payload: dict[str, Any] = item.normalized_payload
        business_no = str(payload.get("business_no") or f"LEG-{batch.id}-{item.row_number}")
        product = ProductAsset.objects.create(
            organization=batch.organization,
            business_no=business_no,
            name=str(payload["name"]),
            brand_code=str(payload.get("brand_code") or ""),
            category_code=str(payload["category_code"]),
            source_type=ProductSourceType.LEGACY_IMPORT,
            lifecycle_status=ProductLifecycleStatus.DEVELOPING,
            product_owner=actor,
        )
        completeness = (
            CompletenessStatus.COMPLETE
            if payload.get("sku_code") and payload.get("barcode")
            else CompletenessStatus.PARTIAL
        )
        change_set = ProductChangeSet.objects.create(
            organization=batch.organization,
            change_type=ChangeSetType.LEGACY_BASELINE,
            status=ChangeSetStatus.DRAFT,
            product=product,
            migration_batch_id=batch.id,
            title=f"Legacy baseline: {product.name}",
            definition_summary=str(payload.get("specification") or ""),
            completeness_status=completeness,
            change_scope={"import_row_number": item.row_number, "payload": payload},
            created_by=actor,
        )
        item.baseline_change_set = change_set
        item.target_product = product
        item.item_status = ImportItemStatus.CONFIRMED
        item.decision = ImportItemDecision.CREATE
        item.save(
            update_fields=[
                "baseline_change_set",
                "target_product",
                "item_status",
                "decision",
                "updated_at",
            ]
        )
        return ConfirmImportItemResult(
            row_number=item.row_number,
            baseline_public_id=str(change_set.public_id),
            item_status=item.item_status,
        )

    def _link_existing_product(
        self,
        *,
        batch: ImportBatch,
        item: ImportItem,
        actor: User,
    ) -> ConfirmImportItemResult:
        if item.target_product_id is None:
            item.item_status = ImportItemStatus.FAILED
            item.error_code = "LINK_TARGET_REQUIRED"
            item.save(update_fields=["item_status", "error_code", "updated_at"])
            return ConfirmImportItemResult(
                row_number=item.row_number,
                baseline_public_id=None,
                item_status=item.item_status,
            )

        product = ProductAsset.objects.get(
            pk=item.target_product_id,
            organization_id=batch.organization_id,
        )
        change_set = ProductChangeSet.objects.create(
            organization=batch.organization,
            change_type=ChangeSetType.LEGACY_BASELINE,
            status=ChangeSetStatus.DRAFT,
            product=product,
            migration_batch_id=batch.id,
            title=f"Legacy baseline link: {product.name}",
            definition_summary=str(item.normalized_payload.get("specification") or ""),
            completeness_status=CompletenessStatus.PARTIAL,
            change_scope={
                "import_row_number": item.row_number,
                "payload": item.normalized_payload,
                "linked_existing_product": True,
            },
            created_by=actor,
        )
        item.baseline_change_set = change_set
        item.target_product = product
        item.item_status = ImportItemStatus.CONFIRMED
        item.save(
            update_fields=[
                "baseline_change_set",
                "target_product",
                "item_status",
                "updated_at",
            ]
        )
        return ConfirmImportItemResult(
            row_number=item.row_number,
            baseline_public_id=str(change_set.public_id),
            item_status=item.item_status,
        )


@dataclass
class DecideImportItem:
    context: CommandContext
    batch_public_id: UUID
    row_number: int
    decision: str
    target_product_public_id: UUID | None = None

    def execute(self) -> ImportItem:
        actor = self.context.actor
        auth_decision = authorize(
            subject_for(actor),
            action="migration.review",
            resource=ResourceDescriptor(
                resource_type="migration",
                public_id=None,
                organization_id=actor.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not auth_decision.allowed:
            raise PermissionDeniedError()

        item = (
            ImportItem.objects.select_related("batch")
            .filter(
                batch__public_id=self.batch_public_id,
                batch__organization_id=actor.organization_id,
                row_number=self.row_number,
            )
            .first()
        )
        if item is None:
            raise PermissionDeniedError()

        if self.decision not in ImportItemDecision.values:
            raise PermissionDeniedError()

        item.decision = self.decision
        if self.target_product_public_id is not None:
            product = ProductAsset.objects.filter(
                public_id=self.target_product_public_id,
                organization_id=actor.organization_id,
            ).first()
            if product is None:
                raise PermissionDeniedError()
            item.target_product = product
            item.save(update_fields=["decision", "target_product", "updated_at"])
        else:
            item.save(update_fields=["decision", "updated_at"])
        return item
