"""Publication preflight checks for product change sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.products.models import (
    AttributeConfirmation,
    AttributeGroupValue,
    ChangeSetStatus,
    ChangeSetType,
    ConfirmationDecision,
    NutritionTable,
    ProductChangeSet,
    ProductMaterial,
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
        blocks.extend(_baseline_blocks(change_set))
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
    current = current_baseline_fingerprint(
        product=change_set.product,
        base_version=change_set.base_version,
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
