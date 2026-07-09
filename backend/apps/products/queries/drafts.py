"""Read serialization for product drafts."""

from __future__ import annotations

from typing import Any

from apps.products.models import ProductDraft


def serialize_product_draft_detail(draft: ProductDraft) -> dict[str, Any]:
    asset = draft.product_asset
    target = draft.target_product_asset
    return {
        "public_id": str(draft.public_id),
        "draft_type": draft.draft_type,
        "status": draft.status,
        "title": draft.title,
        "definition_summary": draft.definition_summary,
        "product_asset_public_id": str(asset.public_id),
        "product_asset_name": asset.name,
        "target_product_asset_public_id": (str(target.public_id) if target else None),
        "candidate_public_id": str(draft.project_candidate.public_id),
    }
