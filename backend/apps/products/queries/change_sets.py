"""Read serialization for product change sets."""

from __future__ import annotations

from typing import Any

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.products.models import (
    AttributeConfirmation,
    AttributeGroupValue,
    ProductChangeSet,
)
from apps.products.services.diff_change_set import BuildProductChangeSetDiff


def _can_reassign_confirmer(*, actor: User, change_set: ProductChangeSet) -> bool:
    return authorize(
        subject_for(actor),
        action="confirmer.reassign",
        resource=ResourceDescriptor(
            resource_type="product_change_set",
            public_id=change_set.public_id,
            organization_id=change_set.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


def serialize_change_set_detail(change_set: ProductChangeSet, *, actor: User) -> dict[str, Any]:
    group_values = list(
        AttributeGroupValue.objects.filter(change_set=change_set)
        .select_related("group_definition", "assigned_confirmer")
        .order_by("group_definition__display_order", "group_definition__group_code")
    )
    confirmations_by_group_id = _active_confirmations_by_group_value(group_values)

    attribute_groups: list[dict[str, Any]] = []
    for group_value in group_values:
        attribute_groups.append(
            {
                "public_id": str(group_value.public_id),
                "group_code": group_value.group_definition.group_code,
                "group_name": group_value.group_definition.name,
                "requires_confirmation": group_value.group_definition.requires_confirmation,
                "content_hash": group_value.content_hash,
                "values_json": group_value.values_json,
                "confirmation_status": _confirmation_status(
                    group_value=group_value,
                    confirmation=confirmations_by_group_id.get(group_value.id),
                ),
                "assigned_confirmer_public_id": (
                    str(group_value.assigned_confirmer.public_id)
                    if group_value.assigned_confirmer is not None
                    else None
                ),
            }
        )

    return {
        "public_id": str(change_set.public_id),
        "change_type": change_set.change_type,
        "status": change_set.status,
        "title": change_set.title,
        "version_no": change_set.version_no,
        "product_public_id": str(change_set.product.public_id),
        "change_scope": change_set.change_scope or {},
        "attribute_groups": attribute_groups,
        "can_reassign_confirmer": _can_reassign_confirmer(actor=actor, change_set=change_set),
    }


def serialize_change_set_diff(*, actor: User, change_set: ProductChangeSet) -> dict[str, Any]:
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


def _active_confirmations_by_group_value(
    group_values: list[AttributeGroupValue],
) -> dict[int, AttributeConfirmation]:
    group_value_ids = [row.id for row in group_values]
    if not group_value_ids:
        return {}

    content_hash_by_id = {row.id: row.content_hash for row in group_values}
    rows = AttributeConfirmation.objects.filter(
        group_value_id__in=group_value_ids,
        superseded_at__isnull=True,
    ).order_by("group_value_id", "-confirmed_at")
    result: dict[int, AttributeConfirmation] = {}
    for confirmation in rows:
        if confirmation.group_value_id in result:
            continue
        if confirmation.content_hash != content_hash_by_id.get(confirmation.group_value_id):
            continue
        result[confirmation.group_value_id] = confirmation
    return result


def _confirmation_status(
    *,
    group_value: AttributeGroupValue,
    confirmation: AttributeConfirmation | None,
) -> str:
    if confirmation is not None:
        return confirmation.decision
    if group_value.group_definition.requires_confirmation:
        return "PENDING"
    return "NONE"
