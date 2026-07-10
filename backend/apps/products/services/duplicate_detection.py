"""Duplicate candidate detection for legacy product import rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from apps.products.models import SKU, ImportItem, ProductAsset


@dataclass(frozen=True)
class DuplicateCandidate:
    match_type: str
    blocking: bool
    product_public_id: str | None
    sku_public_id: str | None
    message: str


def _normalize_name_spec(name: str, specification: str) -> str:
    combined = f"{name} {specification}".lower()
    return re.sub(r"\s+", " ", combined).strip()


@dataclass
class DetectProductImportDuplicates:
    item: ImportItem

    def execute(self) -> list[DuplicateCandidate]:
        payload: dict[str, Any] = self.item.normalized_payload
        organization_id = self.item.organization_id
        candidates: list[DuplicateCandidate] = []

        external_id = str(payload.get("external_id") or payload.get("business_no") or "").strip()
        if external_id:
            product = ProductAsset.objects.filter(
                organization_id=organization_id,
                business_no=external_id,
            ).first()
            if product is not None:
                candidates.append(
                    DuplicateCandidate(
                        match_type="EXTERNAL_ID_EXACT",
                        blocking=True,
                        product_public_id=str(product.public_id),
                        sku_public_id=None,
                        message="Business number already exists.",
                    )
                )
            sku = SKU.objects.filter(
                organization_id=organization_id,
                sku_code=external_id,
            ).first()
            if sku is not None:
                candidates.append(
                    DuplicateCandidate(
                        match_type="EXTERNAL_ID_EXACT",
                        blocking=True,
                        product_public_id=str(sku.product_version.product.public_id),
                        sku_public_id=str(sku.public_id),
                        message="SKU code already exists.",
                    )
                )

        barcode = str(payload.get("barcode") or "").strip()
        if barcode:
            sku = SKU.objects.filter(organization_id=organization_id, barcode=barcode).first()
            if sku is not None:
                candidates.append(
                    DuplicateCandidate(
                        match_type="BARCODE_EXACT",
                        blocking=True,
                        product_public_id=str(sku.product_version.product.public_id),
                        sku_public_id=str(sku.public_id),
                        message="Barcode already exists.",
                    )
                )

        name = str(payload.get("name") or "").strip()
        specification = str(payload.get("specification") or "").strip()
        if name:
            normalized = _normalize_name_spec(name, specification)
            for sku in SKU.objects.filter(
                organization_id=organization_id,
                product_version__product__name=name,
            ).select_related("product_version__product"):
                if _normalize_name_spec(sku.name, sku.specification) == normalized:
                    product = sku.product_version.product
                    candidates.append(
                        DuplicateCandidate(
                            match_type="NAME_SPEC_SIMILAR",
                            blocking=False,
                            product_public_id=str(product.public_id),
                            sku_public_id=str(sku.public_id),
                            message="Name and specification match an existing SKU.",
                        )
                    )

        brand_code = str(payload.get("brand_code") or "").strip()
        category_code = str(payload.get("category_code") or "").strip()
        net_content_value = str(payload.get("net_content_value") or "").strip()
        net_content_unit = str(payload.get("net_content_unit") or "").strip()
        if brand_code and category_code and net_content_value and net_content_unit:
            for product in ProductAsset.objects.filter(
                organization_id=organization_id,
                brand_code=brand_code,
                category_code=category_code,
            ):
                for sku in SKU.objects.filter(
                    product_version__product=product,
                    net_content_value=net_content_value,
                    net_content_unit=net_content_unit,
                ):
                    candidates.append(
                        DuplicateCandidate(
                            match_type="BRAND_CATEGORY_NET_SIMILAR",
                            blocking=False,
                            product_public_id=str(product.public_id),
                            sku_public_id=str(sku.public_id),
                            message="Brand, category and net content match an existing product.",
                        )
                    )

        return candidates


def serialize_candidates(candidates: list[DuplicateCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "match_type": candidate.match_type,
            "blocking": candidate.blocking,
            "product_public_id": candidate.product_public_id,
            "sku_public_id": candidate.sku_public_id,
            "message": candidate.message,
        }
        for candidate in candidates
    ]
