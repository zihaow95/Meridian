"""Publication validation rules for effective time and channel integrity."""

from __future__ import annotations

import pytest

from apps.products.models import ChangeSetStatus, ChangeSetType
from apps.products.services.validate_publication import ValidateProductPublication


@pytest.mark.django_db
def test_unapproved_change_set_is_blocked(change_set) -> None:
    result = ValidateProductPublication(
        actor=change_set.created_by,
        change_set_public_id=change_set.public_id,
    ).execute()
    assert "CHANGE_SET_NOT_APPROVED" in {block.code for block in result.blocks}


@pytest.mark.django_db
def test_baseline_change_is_blocked(iteration_change_set) -> None:
    iteration_change_set.status = ChangeSetStatus.APPROVED
    iteration_change_set.save(update_fields=["status", "updated_at"])

    iteration_change_set.base_version.definition_summary = "Changed after snapshot"
    iteration_change_set.base_version.save(update_fields=["definition_summary", "updated_at"])

    blocked = ValidateProductPublication(
        actor=iteration_change_set.created_by,
        change_set_public_id=iteration_change_set.public_id,
    ).execute()
    assert "PRODUCT_BASELINE_CHANGED" in {block.code for block in blocked.blocks}


@pytest.mark.django_db
def test_new_product_change_set_has_no_baseline_block(ready_change_set) -> None:
    assert ready_change_set.change_type == ChangeSetType.NEW_PRODUCT
    result = ValidateProductPublication(
        actor=ready_change_set.approved_by,
        change_set_public_id=ready_change_set.public_id,
    ).execute()
    assert "PRODUCT_BASELINE_CHANGED" not in {block.code for block in result.blocks}


@pytest.mark.django_db
def test_missing_effective_from_blocks_publication(ready_change_set) -> None:
    scope = dict(ready_change_set.change_scope or {})
    scope.pop("effective_from", None)
    ready_change_set.change_scope = scope
    ready_change_set.save(update_fields=["change_scope", "updated_at"])

    result = ValidateProductPublication(
        actor=ready_change_set.approved_by,
        change_set_public_id=ready_change_set.public_id,
    ).execute()
    assert "PRODUCT_EFFECTIVE_FROM_REQUIRED" in {block.code for block in result.blocks}


@pytest.mark.django_db
def test_unknown_channel_sku_blocks_publication(ready_change_set) -> None:
    scope = dict(ready_change_set.change_scope or {})
    scope["channels"] = [{"sku_code": "MISSING", "channel_code": "TMALL"}]
    ready_change_set.change_scope = scope
    ready_change_set.save(update_fields=["change_scope", "updated_at"])

    result = ValidateProductPublication(
        actor=ready_change_set.approved_by,
        change_set_public_id=ready_change_set.public_id,
    ).execute()
    assert "PRODUCT_CHANNEL_SKU_UNKNOWN" in {block.code for block in result.blocks}
