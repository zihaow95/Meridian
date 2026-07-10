"""Phase 3 product permission actions must be seeded by migration."""

from __future__ import annotations

import pytest

from apps.authorization.models.role import PermissionAction


@pytest.mark.django_db
def test_phase_3_product_actions_are_seeded() -> None:
    required = {
        "product.search",
        "product.read_basic",
        "product.read_sensitive",
        "product_version.history.read",
        "product_draft.create",
        "product_draft.edit_group",
        "product_draft.submit",
        "attribute_group.confirm",
        "attribute_group.return",
        "confirmer.reassign",
        "product.publish_new",
        "product.publish_iteration",
        "product.publish_baseline",
        "product.correct_baseline",
        "product_material.preview",
        "product_material.download_original",
        "product.export",
        "external_binding.manage",
        "migration.upload",
        "migration.review",
        "migration.confirm",
    }
    seeded = set(PermissionAction.objects.values_list("action_code", flat=True))
    assert required <= seeded
