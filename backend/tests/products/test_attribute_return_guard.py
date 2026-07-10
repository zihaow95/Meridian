"""Guards on attribute return for immutable change sets."""

from __future__ import annotations

import pytest

from apps.platform.application.command import CommandContext
from apps.products.errors import ChangeSetNotEditable
from apps.products.models import ChangeSetStatus
from apps.products.services.confirm_attribute_group import ReturnAttributeGroup


@pytest.mark.django_db
def test_return_attribute_group_rejects_published_change_set(
    ready_change_set,
    product_director,
    grant_action,
) -> None:
    grant_action(
        product_director,
        "attribute_group.return",
        "product_change_set",
        role_code="PRODUCT_DIRECTOR",
    )
    ready_change_set.status = ChangeSetStatus.PUBLISHED
    ready_change_set.save(update_fields=["status", "updated_at"])

    with pytest.raises(ChangeSetNotEditable):
        ReturnAttributeGroup(
            context=CommandContext.for_actor(product_director),
            change_set_public_id=ready_change_set.public_id,
            group_value_public_id=ready_change_set.public_id,
            content_hash="hash",
            comment="retry",
        ).execute()
