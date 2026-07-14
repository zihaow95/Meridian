"""Create a minimal product change set shell from an approved project candidate."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db import IntegrityError

from apps.identity.models.user import User
from apps.opportunities.models import CandidateType, ProjectCandidate
from apps.products.models import (
    ChangeSetStatus,
    ChangeSetType,
    ProductAsset,
    ProductChangeSet,
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
        change_type = ChangeSetType.ITERATION
        target_asset_for_set = target_asset
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
        change_type = ChangeSetType.NEW_PRODUCT
        target_asset_for_set = None

    try:
        change_set = ProductChangeSet.objects.create(
            organization=candidate.organization,
            change_type=change_type,
            status=ChangeSetStatus.DRAFT,
            product=product_asset,
            target_product_asset=target_asset_for_set,
            project_candidate=candidate,
            project=project,
            title=candidate.name,
            definition_summary=candidate.resource_risk_summary,
        )
    except IntegrityError as exc:
        raise ProjectCreationFailed(message="Product draft already exists for candidate.") from exc

    return product_asset, ProductDraft.objects.get(pk=change_set.pk)
