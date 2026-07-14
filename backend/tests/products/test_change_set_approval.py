"""Submit and approve are separate decisions; submitters cannot self-approve."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import ChangeSetStatus, ProductChangeSet
from apps.products.services.workflow_change_set import (
    ApproveProductChangeSet,
    SubmitProductChangeSetConfirmation,
)


@pytest.mark.django_db
def test_product_owner_can_submit_but_cannot_approve_own_change_set(
    change_set: ProductChangeSet,
    product_manager: User,
) -> None:
    submitted = SubmitProductChangeSetConfirmation(
        context=CommandContext.for_actor(product_manager),
        change_set_public_id=change_set.public_id,
    ).execute()
    assert submitted.status == ChangeSetStatus.IN_CONFIRMATION

    with pytest.raises(PermissionDeniedError):
        ApproveProductChangeSet(
            context=CommandContext.for_actor(product_manager),
            change_set_public_id=change_set.public_id,
        ).execute()


@pytest.mark.django_db
def test_product_director_with_approve_action_can_approve(
    change_set: ProductChangeSet,
    product_manager: User,
    product_director: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(
        product_director,
        "product_change_set.approve",
        "product_change_set",
        role_code="PRODUCT_DIRECTOR",
    )
    SubmitProductChangeSetConfirmation(
        context=CommandContext.for_actor(product_manager),
        change_set_public_id=change_set.public_id,
    ).execute()

    approved = ApproveProductChangeSet(
        context=CommandContext.for_actor(product_director),
        change_set_public_id=change_set.public_id,
    ).execute()
    assert approved.status == ChangeSetStatus.APPROVED
    assert approved.approved_by_id == product_director.id
