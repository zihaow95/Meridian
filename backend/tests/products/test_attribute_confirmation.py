"""Attribute group professional confirmation lifecycle."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.products.models import ConfirmationDecision
from apps.products.services.confirm_attribute_group import ApproveAttributeGroup
from apps.products.services.edit_change_set import EditProductChangeSet


@pytest.fixture
def confirmer(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        another_active_user,
        "attribute_group.confirm",
        "product_change_set",
        role_code="QUALITY_LEAD",
    )
    return another_active_user


@pytest.fixture
def confirmed_group_value(change_set, confirmer, published_product_schema):
    del published_product_schema
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
    ).execute()
    change_set.refresh_from_db()
    ApproveAttributeGroup(
        context=CommandContext.for_actor(confirmer),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_value.public_id,
        content_hash=group_value.content_hash,
    ).execute()
    return group_value


@pytest.mark.django_db
def test_editing_confirmed_attribute_group_supersedes_old_confirmation(
    change_set,
    confirmed_group_value,
) -> None:
    group_value = confirmed_group_value
    change_set.refresh_from_db()
    EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code=group_value.group_definition.group_code,
        values={"core_selling_points": "Updated value"},
    ).execute()
    confirmation = group_value.confirmations.get(decision=ConfirmationDecision.APPROVED)
    confirmation.refresh_from_db()
    assert confirmation.superseded_at is not None
