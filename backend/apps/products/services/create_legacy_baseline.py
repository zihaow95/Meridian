"""The single writer for a legacy baseline draft.

Both the item-by-item form and the spreadsheet importer end here. What differs
between them — who authorizes, which row, which batch — stays with the caller;
creating the product asset and its baseline change set happens only here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
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

REQUIRED_PAYLOAD_FIELDS = ("name", "category_code")
_READY_ITEM_STATUSES = frozenset({ImportItemStatus.VALID, ImportItemStatus.DUPLICATE_REVIEW})


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
            # Import-batch confirmation already holds migration.confirm; the
            # item-by-item form uses legacy_baseline.draft.create. Either path
            # must re-check inside the writer so an internal call cannot widen.
            import_item: ImportItem | None = None
            if self.migration_batch_id is not None:
                batch, import_item = self._locked_import_item(actor.organization_id)
                action = "migration.confirm"
                resource_type = "migration"
                public_id = None
                audit_action = "legacy_baseline.draft.create"
            else:
                batch = None
                action = "legacy_baseline.draft.create"
                resource_type = "product_change_set"
                public_id = self.existing_product.public_id if self.existing_product else None
                audit_action = "legacy_baseline.draft.create"
            decision = authorize(
                subject_for(actor),
                action=action,
                resource=ResourceDescriptor(
                    resource_type=resource_type,
                    public_id=public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if import_item is not None and import_item.baseline_change_set_id is not None:
                change_set = (
                    ProductChangeSet.objects.select_related("product")
                    .filter(pk=import_item.baseline_change_set_id)
                    .first()
                )
                if change_set is None:
                    raise ValidationFailedError(
                        message="Import row points at a missing baseline.",
                        details={"blocks": ["IMPORT_BASELINE_MISSING"]},
                    )
                return LegacyBaselineDraft(
                    product=change_set.product,
                    change_set=change_set,
                    created=False,
                )

            if self.idempotency_key:
                replay = find_draft_by_idempotency_key(
                    organization_id=actor.organization_id,
                    idempotency_key=self.idempotency_key,
                )
                if replay is not None:
                    return LegacyBaselineDraft(
                        product=replay.product, change_set=replay, created=False
                    )

            product = self._locked_existing_product(actor.organization_id) or self._create_product(
                actor
            )
            change_set = ProductChangeSet.objects.create(
                organization_id=actor.organization_id,
                change_type=ChangeSetType.LEGACY_BASELINE,
                status=ChangeSetStatus.DRAFT,
                product=product,
                migration_batch_id=batch.id if batch is not None else None,
                title=self._title(product),
                definition_summary=str(self.payload.get("specification") or ""),
                completeness_status=self._completeness(),
                change_scope=self._scope(),
                created_by=actor,
                draft_idempotency_key=self.idempotency_key or None,
            )
            if import_item is not None:
                import_item.baseline_change_set = change_set
                import_item.target_product = product
                import_item.save(
                    update_fields=["baseline_change_set", "target_product", "updated_at"]
                )

            now = self.context.occurred_at or timezone.now()
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code=audit_action,
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "product_public_id": str(product.public_id),
                        "migration_batch_id": batch.id if batch is not None else None,
                        "import_row_number": self.import_row_number,
                        "linked_existing_product": self.existing_product is not None,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="legacy_baseline.draft.created",
                    aggregate_type="product_change_set",
                    aggregate_id=change_set.public_id,
                    payload={
                        "product_public_id": str(product.public_id),
                        "change_set_public_id": str(change_set.public_id),
                        "migration_batch_id": batch.id if batch is not None else None,
                        "import_row_number": self.import_row_number,
                    },
                    occurred_at=now,
                )
            )

        return LegacyBaselineDraft(product=product, change_set=change_set, created=True)

    def _locked_import_item(self, organization_id: int) -> tuple[ImportBatch, ImportItem]:
        batch_id = self.migration_batch_id
        if batch_id is None:
            raise PermissionDeniedError()
        batch = (
            ImportBatch.objects.select_for_update()
            .filter(pk=batch_id, organization_id=organization_id)
            .first()
        )
        if batch is None:
            raise PermissionDeniedError()
        if batch.status not in {
            ImportBatchStatus.PARSED,
            ImportBatchStatus.CONFIRMED,
        }:
            raise ValidationFailedError(
                message="Import batch is not ready for baseline creation.",
                details={"blocks": ["IMPORT_BATCH_NOT_READY"], "status": batch.status},
            )
        if self.import_row_number is None:
            raise ValidationFailedError(
                message="Import baseline creation requires a batch row number.",
                details={"blocks": ["IMPORT_ROW_REQUIRED"]},
            )
        item = (
            ImportItem.objects.select_for_update()
            .filter(
                batch_id=batch.id,
                organization_id=organization_id,
                row_number=self.import_row_number,
            )
            .first()
        )
        if item is None:
            raise ValidationFailedError(
                message="Import row does not belong to this batch.",
                details={
                    "blocks": ["IMPORT_ROW_NOT_IN_BATCH"],
                    "row_number": self.import_row_number,
                },
            )
        if item.normalized_payload != self.payload:
            raise ValidationFailedError(
                message="Import payload does not match the locked import row.",
                details={"blocks": ["IMPORT_PAYLOAD_MISMATCH"], "row_number": item.row_number},
            )
        if item.item_status not in _READY_ITEM_STATUSES:
            raise ValidationFailedError(
                message="Import row is not ready for baseline creation.",
                details={
                    "blocks": ["IMPORT_ROW_NOT_READY"],
                    "row_number": item.row_number,
                    "item_status": item.item_status,
                },
            )
        if item.decision == ImportItemDecision.SKIP:
            raise ValidationFailedError(
                message="Import row was decided as SKIP.",
                details={"blocks": ["IMPORT_ROW_SKIPPED"], "row_number": item.row_number},
            )
        if item.decision == ImportItemDecision.PENDING:
            if item.item_status == ImportItemStatus.DUPLICATE_REVIEW:
                raise ValidationFailedError(
                    message="Duplicate import rows require an explicit CREATE or LINK decision.",
                    details={
                        "blocks": ["IMPORT_DECISION_REQUIRED"],
                        "row_number": item.row_number,
                    },
                )
            if self.existing_product is not None:
                raise ValidationFailedError(
                    message="Import CREATE path cannot bind an existing product.",
                    details={
                        "blocks": ["IMPORT_CREATE_TARGET_FORBIDDEN"],
                        "row_number": item.row_number,
                    },
                )
            # Persist the implicit CREATE decision in the same locked transaction
            # so retries and concurrent callers see an authoritative fact.
            item.decision = ImportItemDecision.CREATE
            item.save(update_fields=["decision", "updated_at"])
        elif item.decision == ImportItemDecision.LINK:
            if (
                self.existing_product is None
                or item.target_product_id is None
                or self.existing_product.pk != item.target_product_id
            ):
                raise ValidationFailedError(
                    message="Import LINK decision requires the locked target product.",
                    details={
                        "blocks": ["IMPORT_LINK_TARGET_MISMATCH"],
                        "row_number": item.row_number,
                    },
                )
        elif item.decision == ImportItemDecision.CREATE:
            if self.existing_product is not None:
                raise ValidationFailedError(
                    message="Import CREATE path cannot bind an existing product.",
                    details={
                        "blocks": ["IMPORT_CREATE_TARGET_FORBIDDEN"],
                        "row_number": item.row_number,
                    },
                )
        else:
            raise ValidationFailedError(
                message="Import row decision is not accepted for baseline creation.",
                details={
                    "blocks": ["IMPORT_DECISION_REQUIRED"],
                    "row_number": item.row_number,
                    "decision": item.decision,
                },
            )
        return batch, item

    def _locked_existing_product(self, organization_id: int) -> ProductAsset | None:
        if self.existing_product is None:
            return None
        product = (
            ProductAsset.objects.select_for_update()
            .filter(pk=self.existing_product.pk, organization_id=organization_id)
            .first()
        )
        if product is None:
            raise PermissionDeniedError()
        return product

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
