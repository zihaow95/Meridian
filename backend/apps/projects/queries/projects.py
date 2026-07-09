"""Read serialization for projects."""

from __future__ import annotations

from typing import Any

from apps.projects.models import Project


def serialize_project_detail(project: Project) -> dict[str, Any]:
    leader = project.leader
    deputy_leader = project.deputy_leader
    product_asset = project.product_asset
    product_draft = project.product_draft
    return {
        "public_id": str(project.public_id),
        "business_no": project.business_no,
        "name": project.name,
        "project_type": project.project_type,
        "status": project.status,
        "candidate_public_id": str(project.candidate.public_id),
        "leader_public_id": str(leader.public_id),
        "deputy_leader_public_id": (
            str(deputy_leader.public_id) if deputy_leader is not None else None
        ),
        "product_asset_public_id": (
            str(product_asset.public_id) if product_asset is not None else None
        ),
        "product_draft_public_id": (
            str(product_draft.public_id) if product_draft is not None else None
        ),
        "opportunity_sources": [
            {
                "opportunity_public_id": str(item.opportunity.public_id),
                "source_role": item.source_role,
            }
            for item in project.opportunity_sources.select_related("opportunity").all()
        ],
    }
