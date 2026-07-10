"""Read serialization for product change sets."""

from __future__ import annotations

from typing import Any

from apps.products.models import ProductChangeSet
from apps.products.services.diff_change_set import BuildProductChangeSetDiff


def serialize_change_set_detail(change_set: ProductChangeSet) -> dict[str, Any]:
    return {
        "public_id": str(change_set.public_id),
        "change_type": change_set.change_type,
        "status": change_set.status,
        "title": change_set.title,
        "version_no": change_set.version_no,
        "product_public_id": str(change_set.product.public_id),
    }


def serialize_change_set_diff(*, actor, change_set: ProductChangeSet) -> dict[str, Any]:
    diff = BuildProductChangeSetDiff(
        actor=actor,
        change_set_public_id=change_set.public_id,
    ).execute()
    return {
        "change_set_public_id": str(diff.change_set_public_id),
        "changed_fields": [
            {
                "group_code": field.group_code,
                "field_code": field.field_code,
                "field_name": field.field_name,
                "old_value": field.old_value,
                "new_value": field.new_value,
            }
            for field in diff.changed_fields
        ],
    }
