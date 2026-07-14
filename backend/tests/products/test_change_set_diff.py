"""Product change set diff against baseline snapshots."""

from __future__ import annotations

import pytest

from apps.platform.application.command import CommandContext
from apps.products.models import AttributeOwnerType
from apps.products.services.diff_change_set import BuildProductChangeSetDiff
from apps.products.services.edit_change_set import EditProductChangeSet


@pytest.mark.django_db
def test_change_set_diff_compares_by_stable_field_code(iteration_change_set) -> None:
    EditProductChangeSet(
        context=CommandContext.for_actor(iteration_change_set.created_by),
        change_set_public_id=iteration_change_set.public_id,
        version_no=iteration_change_set.version_no,
        group_code="QUALITY_COMPLIANCE",
        owner_type=AttributeOwnerType.VERSION,
        owner_id=iteration_change_set.base_version_id,
        values={"storage_condition": "Keep refrigerated"},
    ).execute()
    diff = BuildProductChangeSetDiff(
        actor=iteration_change_set.created_by,
        change_set_public_id=iteration_change_set.public_id,
    ).execute()
    assert diff.changed_fields[0].field_code == "storage_condition"
    assert diff.changed_fields[0].new_value == "Keep refrigerated"
    assert diff.changed_fields[0].field_name == "Storage condition label"
