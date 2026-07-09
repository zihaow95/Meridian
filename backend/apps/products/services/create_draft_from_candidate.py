"""Create a minimal product draft shell from an approved project candidate."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db import IntegrityError

from apps.identity.models.user import User
from apps.opportunities.models import CandidateType, ProjectCandidate
from apps.products.models import (
    DraftStatus,
    DraftType,
    ProductAsset,
    ProductDraft,
    ProductLifecycleStatus,
    ProductSourceType,
)
from apps.projects.errors import ProjectCreationFailed
from apps.projects.models import Project


def create_product_draft(
    *,
    candidate: ProjectCandidate,
    project: Project,
    actor: User,
    now: datetime,
) -> tuple[ProductAsset, ProductDraft]:
    if candidate.case_owner is None:
        raise ProjectCreationFailed(message="Case owner is required to create a product draft.")
    case_owner = candidate.case_owner

    if candidate.candidate_type == CandidateType.PRODUCT_CHANGE:
        if candidate.target_product_id is None:
            raise ProjectCreationFailed(message="Product change requires a target product.")
        target_asset = ProductAsset.objects.filter(
            id=candidate.target_product_id,
            organization_id=candidate.organization_id,
        ).first()
        if target_asset is None:
            raise ProjectCreationFailed(message="Target product asset was not found.")
        product_asset = target_asset
        draft_type = DraftType.PRODUCT_CHANGE
    else:
        product_asset = ProductAsset.objects.create(
            organization=candidate.organization,
            business_no=f"PRD-{uuid.uuid4().hex[:8].upper()}",
            name=candidate.name,
            source_type=ProductSourceType.NEW_PROJECT,
            lifecycle_status=ProductLifecycleStatus.DEVELOPING,
            product_owner=case_owner,
            source_project=project,
        )
        draft_type = DraftType.NEW_PRODUCT
        target_asset = None

    try:
        draft = ProductDraft.objects.create(
            organization=candidate.organization,
            product_asset=product_asset,
            draft_type=draft_type,
            status=DraftStatus.DRAFT,
            target_product_asset=target_asset,
            project_candidate=candidate,
            title=candidate.name,
            definition_summary=candidate.resource_risk_summary,
        )
    except IntegrityError as exc:
        raise ProjectCreationFailed(message="Product draft already exists for candidate.") from exc

    return product_asset, draft
