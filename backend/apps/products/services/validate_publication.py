"""Publication preflight checks for product change sets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.products.models import (
    SKU,
    AttributeConfirmation,
    AttributeGroupValue,
    ChangeSetStatus,
    ChangeSetType,
    ConfirmationDecision,
    NutritionTable,
    ProductChangeSet,
    ProductMaterial,
)
from apps.products.services.attribute_schema import (
    resolve_product_attribute_schema,
    validate_group_values,
)
from apps.products.services.create_change_set import current_baseline_fingerprint
from apps.products.services.materials import validate_material_for_publication


@dataclass(frozen=True)
class PublicationBlock:
    code: str
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class PublicationValidationResult:
    blocks: tuple[PublicationBlock, ...]

    @property
    def can_publish(self) -> bool:
        return not self.blocks


@dataclass
class ValidateProductPublication:
    actor: User
    change_set_public_id: UUID

    def execute(self) -> PublicationValidationResult:
        change_set = (
            ProductChangeSet.objects.select_related("product", "base_version")
            .filter(
                public_id=self.change_set_public_id,
                organization_id=self.actor.organization_id,
            )
            .first()
        )
        if change_set is None:
            raise PermissionDeniedError()

        blocks: list[PublicationBlock] = []
        blocks.extend(_status_blocks(change_set))
        blocks.extend(_core_field_blocks(change_set))
        blocks.extend(_schema_required_blocks(change_set))
        blocks.extend(_sku_blocks(change_set))
        blocks.extend(_channel_blocks(change_set))
        blocks.extend(_baseline_blocks(change_set))
        blocks.extend(_approval_basis_blocks(change_set))
        blocks.extend(_effective_time_blocks(change_set))
        blocks.extend(_confirmation_blocks(change_set))
        blocks.extend(_nutrition_blocks(change_set))
        blocks.extend(_material_blocks(change_set))
        return PublicationValidationResult(blocks=tuple(blocks))


def _status_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    if change_set.status != ChangeSetStatus.APPROVED:
        return [
            PublicationBlock(
                code="CHANGE_SET_NOT_APPROVED",
                message="The change set must be approved before publication.",
                details={"status": change_set.status},
            )
        ]
    return []


def _core_field_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    product = change_set.product
    missing: list[str] = []
    if not product.name.strip():
        missing.append("name")
    if not product.business_no.strip():
        missing.append("business_no")
    if not product.category_code.strip():
        missing.append("category_code")
    if missing:
        return [
            PublicationBlock(
                code="PRODUCT_REQUIRED_FIELD_MISSING",
                message="Core product fields are incomplete.",
                details={"fields": missing},
            )
        ]
    return []


def _schema_required_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    if not change_set.product.category_code:
        return []
    try:
        schema = resolve_product_attribute_schema(
            change_set.organization_id,
            category_code=change_set.product.category_code,
        )
    except Exception:
        return [
            PublicationBlock(
                code="ATTRIBUTE_SCHEMA_NOT_PUBLISHED",
                message="No published attribute schema is available.",
                details={},
            )
        ]

    blocks: list[PublicationBlock] = []
    draft_values = {
        row.group_definition_id: row
        for row in AttributeGroupValue.objects.filter(change_set=change_set).select_related(
            "group_definition",
        )
    }
    for group_definition in schema.group_definitions:
        group_value = draft_values.get(group_definition.id)
        values = group_value.values_json if group_value is not None else {}
        try:
            validate_group_values(group_definition=group_definition, values=values)
        except Exception as exc:
            blocks.append(
                PublicationBlock(
                    code="ATTRIBUTE_VALUE_INVALID",
                    message="Required schema attributes are missing or invalid.",
                    details={
                        "group_code": group_definition.group_code,
                        "reason": str(exc),
                    },
                )
            )
    return blocks


def _sku_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    scope = change_set.change_scope or {}
    sku_rows = scope.get("skus")
    if not isinstance(sku_rows, list) or not sku_rows:
        if change_set.change_type in {ChangeSetType.NEW_PRODUCT, ChangeSetType.ITERATION}:
            return [
                PublicationBlock(
                    code="PRODUCT_SKU_MISSING",
                    message="At least one SKU must be declared before publication.",
                    details={},
                )
            ]
        return []

    blocks: list[PublicationBlock] = []
    seen_codes: set[str] = set()
    seen_barcodes: set[str] = set()
    for row in sku_rows:
        if not isinstance(row, dict):
            continue
        sku_code = str(row.get("sku_code") or "").strip()
        barcode = str(row.get("barcode") or "").strip()
        if not sku_code:
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_SKU_CODE_MISSING",
                    message="SKU code is required.",
                    details={},
                )
            )
            continue
        if sku_code in seen_codes:
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_SKU_CODE_DUPLICATE",
                    message="Duplicate SKU code in change set scope.",
                    details={"sku_code": sku_code},
                )
            )
        seen_codes.add(sku_code)
        if barcode:
            if barcode in seen_barcodes:
                blocks.append(
                    PublicationBlock(
                        code="PRODUCT_BARCODE_DUPLICATE",
                        message="Duplicate barcode in change set scope.",
                        details={"barcode": barcode},
                    )
                )
            conflict = SKU.objects.filter(
                organization_id=change_set.organization_id,
                barcode=barcode,
            ).exists()
            if conflict:
                blocks.append(
                    PublicationBlock(
                        code="PRODUCT_BARCODE_CONFLICT",
                        message="Barcode already exists on another SKU.",
                        details={"barcode": barcode},
                    )
                )
            seen_barcodes.add(barcode)
    return blocks


def _approval_basis_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    if change_set.change_type == ChangeSetType.LEGACY_BASELINE:
        return []
    if not change_set.approved_by_id:
        return [
            PublicationBlock(
                code="CHANGE_SET_NOT_APPROVED",
                message="The change set must be approved before publication.",
                details={},
            )
        ]
    return []


def _effective_time_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    if change_set.change_type not in {ChangeSetType.NEW_PRODUCT, ChangeSetType.ITERATION}:
        return []
    scope = change_set.change_scope or {}
    effective_from = scope.get("effective_from")
    if effective_from in (None, ""):
        return [
            PublicationBlock(
                code="PRODUCT_EFFECTIVE_FROM_REQUIRED",
                message="Publication requires an explicit effective_from timestamp.",
                details={},
            )
        ]
    try:
        parsed = datetime.fromisoformat(str(effective_from).replace("Z", "+00:00"))
    except ValueError:
        return [
            PublicationBlock(
                code="PRODUCT_EFFECTIVE_FROM_INVALID",
                message="effective_from must be an ISO-8601 datetime.",
                details={"effective_from": effective_from},
            )
        ]
    if parsed.tzinfo is None:
        return [
            PublicationBlock(
                code="PRODUCT_EFFECTIVE_FROM_INVALID",
                message="effective_from must include a timezone.",
                details={"effective_from": effective_from},
            )
        ]
    return _scope_conflict_blocks(change_set, effective_from=parsed)


def _scope_conflict_blocks(
    change_set: ProductChangeSet,
    *,
    effective_from: datetime,
) -> list[PublicationBlock]:
    from apps.products.models import ProductVersionScope, VersionScopeStatus

    scope = change_set.change_scope or {}
    scope_rows = scope.get("scopes")
    if not isinstance(scope_rows, list) or not scope_rows:
        return []

    blocks: list[PublicationBlock] = []
    for row in scope_rows:
        if not isinstance(row, dict):
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_SCOPE_INVALID",
                    message="Version scope rows must be objects.",
                    details={},
                )
            )
            continue
        scope_type = str(row.get("scope_type") or "").strip()
        channel_code = str(row.get("channel_code") or "").strip()
        if not scope_type:
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_SCOPE_TYPE_MISSING",
                    message="Version scope type is required.",
                    details={},
                )
            )
            continue
        overlapping = ProductVersionScope.objects.filter(
            product_version__product_id=change_set.product_id,
            scope_type=scope_type,
            channel_code=channel_code,
            status=VersionScopeStatus.EFFECTIVE,
            valid_to__isnull=True,
        )
        if change_set.base_version_id is not None:
            overlapping = overlapping.exclude(product_version_id=change_set.base_version_id)
        if overlapping.exists():
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_SCOPE_CONFLICT",
                    message="An overlapping effective version scope already exists.",
                    details={
                        "scope_type": scope_type,
                        "channel_code": channel_code,
                        "effective_from": effective_from.isoformat(),
                    },
                )
            )
    return blocks


def _channel_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    scope = change_set.change_scope or {}
    channels = scope.get("channels")
    if not isinstance(channels, list) or not channels:
        return []

    sku_codes = {
        str(row.get("sku_code") or "").strip()
        for row in (scope.get("skus") or [])
        if isinstance(row, dict)
    }
    blocks: list[PublicationBlock] = []
    for index, row in enumerate(channels):
        if not isinstance(row, dict):
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_CHANNEL_INVALID",
                    message="Channel configuration rows must be objects.",
                    details={"index": index},
                )
            )
            continue
        sku_code = str(row.get("sku_code") or "").strip()
        channel_code = str(row.get("channel_code") or "").strip()
        if not sku_code or not channel_code:
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_CHANNEL_INCOMPLETE",
                    message="Channel rows require sku_code and channel_code.",
                    details={"index": index},
                )
            )
            continue
        if sku_code not in sku_codes:
            blocks.append(
                PublicationBlock(
                    code="PRODUCT_CHANNEL_SKU_UNKNOWN",
                    message="Channel row references a SKU that is not declared in change_scope.",
                    details={"sku_code": sku_code, "channel_code": channel_code},
                )
            )
    return blocks


def _baseline_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    if change_set.change_type != ChangeSetType.ITERATION:
        return []
    if change_set.base_version_id is None:
        return [
            PublicationBlock(
                code="PRODUCT_BASELINE_MISSING",
                message="Iteration change sets require a baseline version.",
                details={},
            )
        ]
    base_version = change_set.base_version
    assert base_version is not None
    current = current_baseline_fingerprint(
        product=change_set.product,
        base_version=base_version,
    )
    if change_set.base_fingerprint and change_set.base_fingerprint != current:
        return [
            PublicationBlock(
                code="PRODUCT_BASELINE_CHANGED",
                message="The product baseline fingerprint has changed.",
                details={
                    "expected": change_set.base_fingerprint,
                    "current": current,
                },
            )
        ]
    return []


def _confirmation_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    blocks: list[PublicationBlock] = []
    draft_values = AttributeGroupValue.objects.filter(change_set=change_set).select_related(
        "group_definition",
    )
    for group_value in draft_values:
        group_definition = group_value.group_definition
        if not group_definition.requires_confirmation:
            continue
        has_active_confirmation = AttributeConfirmation.objects.filter(
            group_value=group_value,
            content_hash=group_value.content_hash,
            decision=ConfirmationDecision.APPROVED,
            superseded_at__isnull=True,
        ).exists()
        if not has_active_confirmation:
            blocks.append(
                PublicationBlock(
                    code="ATTRIBUTE_CONFIRMATION_REQUIRED",
                    message="A required attribute group confirmation is missing or stale.",
                    details={"group_code": group_definition.group_code},
                )
            )
    return blocks


def _nutrition_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    blocks: list[PublicationBlock] = []
    for table in NutritionTable.objects.filter(change_set=change_set):
        if table.structured_summary_hash != table.label_summary_hash:
            blocks.append(
                PublicationBlock(
                    code="NUTRITION_LABEL_MISMATCH",
                    message="Structured nutrition summary does not match the label file.",
                    details={"nutrition_table_public_id": str(table.public_id)},
                )
            )
    return blocks


def _material_blocks(change_set: ProductChangeSet) -> list[PublicationBlock]:
    blocks: list[PublicationBlock] = []
    for material in ProductMaterial.objects.filter(change_set=change_set).select_related(
        "document_version",
    ):
        error_code = validate_material_for_publication(material)
        if error_code is not None:
            blocks.append(
                PublicationBlock(
                    code=error_code,
                    message="Product material references a non-controlled document version.",
                    details={
                        "material_public_id": str(material.public_id),
                        "document_version_public_id": str(material.document_version.public_id),
                    },
                )
            )
    return blocks
