"""Assigned confirmer object identity for attribute confirmation."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import ChangeSetStatus
from apps.products.services.confirm_attribute_group import (
    ApproveAttributeGroup,
    ReassignAttributeConfirmer,
)
from apps.products.services.edit_change_set import EditProductChangeSet


def _edit_and_assign(
    *,
    change_set,
    confirmer: User,
    group_code: str,
    values: dict[str, str],
    grant_action: Callable[..., None],
):
    grant_action(
        change_set.created_by,
        "confirmer.reassign",
        "product_change_set",
        role_code="PRODUCT_DIRECTOR",
    )
    change_set.refresh_from_db()
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code=group_code,
        values=values,
    ).execute()
    ReassignAttributeConfirmer(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_value.public_id,
        confirmer_user_id=confirmer.id,
    ).execute()
    group_value.refresh_from_db()
    return group_value


@pytest.mark.django_db
def test_assigned_confirmer_can_confirm_without_global_role(
    change_set,
    another_active_user: User,
    published_product_schema,
    grant_action: Callable[..., None],
) -> None:
    del published_product_schema
    group_value = _edit_and_assign(
        change_set=change_set,
        confirmer=another_active_user,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
        grant_action=grant_action,
    )
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
    group_value = _edit_and_assign(
        change_set=change_set,
        confirmer=another_active_user,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
        grant_action=grant_action,
    )
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


@pytest.mark.django_db
def test_assigned_confirmer_cannot_confirm_other_attribute_group(
    change_set,
    another_active_user: User,
    published_product_schema,
    grant_action: Callable[..., None],
) -> None:
    del published_product_schema
    group_a = _edit_and_assign(
        change_set=change_set,
        confirmer=another_active_user,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
        grant_action=grant_action,
    )
    change_set.refresh_from_db()
    group_b = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="QUALITY_COMPLIANCE",
        values={"storage_condition": "Cold"},
    ).execute()
    assert group_a.assigned_confirmer_id == another_active_user.id
    assert group_b.assigned_confirmer_id != another_active_user.id

    ApproveAttributeGroup(
        context=CommandContext.for_actor(another_active_user),
        change_set_public_id=change_set.public_id,
        group_value_public_id=group_a.public_id,
        content_hash=group_a.content_hash,
    ).execute()
    with pytest.raises(PermissionDeniedError):
        ApproveAttributeGroup(
            context=CommandContext.for_actor(another_active_user),
            change_set_public_id=change_set.public_id,
            group_value_public_id=group_b.public_id,
            content_hash=group_b.content_hash,
        ).execute()


@pytest.mark.django_db
def test_product_owner_cannot_confirm_without_assignment(
    change_set,
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
            context=CommandContext.for_actor(change_set.created_by),
            change_set_public_id=change_set.public_id,
            group_value_public_id=group_value.public_id,
            content_hash=group_value.content_hash,
        ).execute()


@pytest.mark.django_db
def test_reassign_confirmer_api_allows_owner_to_assign(
    api_client: APIClient,
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
    api_client.force_authenticate(user=change_set.created_by)
    response = api_client.post(
        f"/api/v1/product-change-sets/{change_set.public_id}/reassign-confirmer",
        {
            "group_value_public_id": str(group_value.public_id),
            "confirmer_public_id": str(another_active_user.public_id),
            "reason": "quality lead",
        },
        format="json",
    )
    assert response.status_code == 200
    groups = {row["public_id"]: row for row in response.json()["attribute_groups"]}
    assert groups[str(group_value.public_id)]["assigned_confirmer_public_id"] == str(
        another_active_user.public_id
    )
