"""Assigned confirmer object identity for attribute confirmation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import ChangeSetStatus
from apps.products.services.confirm_attribute_group import (
    ApproveAttributeGroup,
    ReassignAttributeConfirmer,
)
from apps.products.services.edit_change_set import EditProductChangeSet


@pytest.mark.django_db
def test_assigned_confirmer_can_confirm_without_global_role(
    change_set,
    another_active_user: User,
    published_product_schema,
    grant_action: Callable[..., None],
) -> None:
    del published_product_schema
    grant_action(
        change_set.created_by,
        "confirmer.reassign",
        "product_change_set",
        role_code="PRODUCT_DIRECTOR",
    )
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
    ).execute()
    ReassignAttributeConfirmer(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_value.public_id,
        confirmer_user_id=another_active_user.id,
    ).execute()
    group_value.refresh_from_db()
    assert group_value.assigned_confirmer_id == another_active_user.id

    ApproveAttributeGroup(
        context=CommandContext.for_actor(another_active_user),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_value.public_id,
        content_hash=group_value.content_hash,
    ).execute()
    change_set.refresh_from_db()
    assert change_set.status == ChangeSetStatus.DRAFT


@pytest.mark.django_db
def test_attribute_confirm_does_not_advance_to_in_confirmation(
    change_set,
    another_active_user: User,
    published_product_schema,
    grant_action: Callable[..., None],
) -> None:
    del published_product_schema
    grant_action(
        another_active_user,
        "attribute_group.confirm",
        "product_change_set",
        role_code="QUALITY_LEAD",
    )
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
    ).execute()
    ApproveAttributeGroup(
        context=CommandContext.for_actor(another_active_user),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_value.public_id,
        content_hash=group_value.content_hash,
    ).execute()
    change_set.refresh_from_db()
    assert change_set.status == ChangeSetStatus.DRAFT


@pytest.mark.django_db
def test_unassigned_user_cannot_confirm_by_object_identity_alone(
    change_set,
    another_active_user: User,
    published_product_schema,
) -> None:
    del published_product_schema
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
    ).execute()
    with pytest.raises(PermissionDeniedError):
        ApproveAttributeGroup(
            context=CommandContext.for_actor(another_active_user),
            change_set_public_id=change_set.public_id,
            group_value_public_id=group_value.public_id,
            content_hash=group_value.content_hash,
        ).execute()
