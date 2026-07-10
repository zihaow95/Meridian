"""Read serialization for product drafts."""

from __future__ import annotations

from typing import Any

from apps.products.models import ProductChangeSet


def serialize_product_draft_detail(change_set: ProductChangeSet) -> dict[str, Any]:
    asset = change_set.product
    target = change_set.target_product_asset
    return {
        "public_id": str(change_set.public_id),
        "draft_type": change_set.draft_type,
        "status": change_set.status,
        "title": change_set.title,
        "definition_summary": change_set.definition_summary,
        "product_asset_public_id": str(asset.public_id),
        "product_asset_name": asset.name,
        "target_product_asset_public_id": (str(target.public_id) if target else None),
        "candidate_public_id": str(change_set.project_candidate.public_id),
    }
