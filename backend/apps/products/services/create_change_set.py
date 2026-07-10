"""Create product change sets for new products and iterations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ChangeSetStatus,
    ChangeSetType,
    ProductAsset,
    ProductChangeSet,
    ProductVersion,
)
from apps.products.services.attribute_schema import compute_attribute_content_hash


def compute_baseline_fingerprint(
    *, product: ProductAsset, base_version: ProductVersion | None
) -> str:
    payload: dict[str, Any] = {
        "product_id": product.id,
        "product_name": product.name,
        "base_version_id": base_version.id if base_version is not None else None,
    }
    if base_version is not None:
        payload["version_code"] = base_version.version_code
        payload["definition_summary"] = base_version.definition_summary
        baseline_values = AttributeGroupValue.objects.filter(
            organization_id=product.organization_id,
            owner_type=AttributeOwnerType.VERSION,
            owner_id=base_version.id,
            value_status=AttributeValueStatus.EFFECTIVE,
            change_set__isnull=True,
        ).select_related("group_definition")
        payload["attribute_groups"] = {
            row.group_definition.group_code: row.values_json for row in baseline_values
        }
    return compute_attribute_content_hash(payload)


@dataclass
class CreateProductChangeSet:
    context: CommandContext
    change_type: str
    product: ProductAsset
    title: str
    project_candidate_id: int
    project_id: int | None = None
    base_version: ProductVersion | None = None
    definition_summary: str = ""

    def execute(self) -> ProductChangeSet:
        actor = self.context.actor
        with transaction.atomic():
            base_fingerprint = ""
            if self.change_type == ChangeSetType.ITERATION:
                if self.base_version is None:
                    raise ValueError("Iteration change sets require a base version.")
                base_fingerprint = compute_baseline_fingerprint(
                    product=self.product,
                    base_version=self.base_version,
                )
            return ProductChangeSet.objects.create(
                organization=self.product.organization,
                change_type=self.change_type,
                status=ChangeSetStatus.DRAFT,
                product=self.product,
                base_version=self.base_version,
                base_fingerprint=base_fingerprint,
                project_candidate_id=self.project_candidate_id,
                project_id=self.project_id,
                title=self.title,
                definition_summary=self.definition_summary,
                created_by=actor,
            )


def current_baseline_fingerprint(*, product: ProductAsset, base_version: ProductVersion) -> str:
    return compute_baseline_fingerprint(product=product, base_version=base_version)
