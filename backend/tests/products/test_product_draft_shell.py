"""Product draft shell invariants."""

from __future__ import annotations

import pytest

from apps.platform.application.command import CommandContext
from apps.products.models import DraftStatus, DraftType, ProductDraft, ProductLifecycleStatus
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject


@pytest.mark.django_db
def test_new_product_draft_is_developing_shell(approved_candidate, boss) -> None:
    result = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="draft-shell",
    ).execute()

    draft = ProductDraft.objects.get(public_id=result.product_draft.public_id)
    assert draft.draft_type == DraftType.NEW_PRODUCT
    assert draft.status == DraftStatus.DRAFT
    assert draft.product_asset.lifecycle_status == ProductLifecycleStatus.DEVELOPING
    assert draft.project_candidate_id == approved_candidate.id
