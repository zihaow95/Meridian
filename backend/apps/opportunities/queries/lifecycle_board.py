"""Unified lifecycle board: pre-project opportunities and created projects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.identity.models.user import User
from apps.opportunities.models import (
    CandidateSource,
    Opportunity,
    ProjectCandidate,
    ProposalStatus,
)
from apps.opportunities.queries.opportunities import list_my_opportunities
from apps.projects.models import Project

LIFECYCLE_STAGE_PROPOSAL = "PROPOSAL"
LIFECYCLE_STAGE_CASE = "CASE"
LIFECYCLE_STAGE_PROJECT = "PROJECT"
LIFECYCLE_STAGE_DEFERRED = "DEFERRED"
LIFECYCLE_STAGE_PASSED = "PASSED"

_PROPOSAL_STATUSES = {
    ProposalStatus.DRAFT,
    ProposalStatus.NEEDS_INFO,
    ProposalStatus.SUBMITTED,
    ProposalStatus.IN_REVIEW,
}
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class LifecycleBoardPage:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total_count: int
    has_more: bool


def _opportunity_lifecycle_stage(opportunity: Opportunity) -> str:
    if opportunity.proposal_status in _PROPOSAL_STATUSES:
        return LIFECYCLE_STAGE_PROPOSAL
    if opportunity.proposal_status == ProposalStatus.DEFERRED:
        return LIFECYCLE_STAGE_DEFERRED
    if opportunity.proposal_status == ProposalStatus.PASSED:
        return LIFECYCLE_STAGE_PASSED
    return LIFECYCLE_STAGE_CASE


def _primary_candidate(opportunity: Opportunity) -> ProjectCandidate | None:
    source = (
        CandidateSource.objects.filter(
            opportunity=opportunity,
            is_active=True,
            source_role="PRIMARY",
        )
        .select_related("candidate")
        .first()
    )
    return source.candidate if source is not None else None


def _projected_opportunity_ids() -> set[int]:
    return set(
        CandidateSource.objects.filter(candidate__project_id__isnull=False).values_list(
            "opportunity_id",
            flat=True,
        )
    )


def _visible_projects(user: User) -> list[Project]:
    now = timezone.now()
    member_project_ids = (
        Project.objects.filter(
            members__user=user,
            members__active_from__lte=now,
        )
        .filter(Q(members__active_to__isnull=True) | Q(members__active_to__gt=now))
        .values_list("id", flat=True)
    )
    return list(
        Project.objects.filter(organization_id=user.organization_id)
        .filter(Q(leader=user) | Q(id__in=member_project_ids))
        .select_related("leader", "candidate")
        .order_by("-updated_at")
    )


def _serialize_opportunity_item(opportunity: Opportunity) -> dict[str, Any]:
    candidate = _primary_candidate(opportunity)
    owner = opportunity.proposal_owner
    return {
        "item_type": "OPPORTUNITY",
        "public_id": str(opportunity.public_id),
        "business_no": opportunity.business_no,
        "title": opportunity.title,
        "lifecycle_stage": _opportunity_lifecycle_stage(opportunity),
        "status": opportunity.proposal_status,
        "owner_public_id": str(owner.public_id),
        "owner_display_name": owner.display_name,
        "candidate_public_id": (str(candidate.public_id) if candidate is not None else None),
        "updated_at": opportunity.updated_at.isoformat(),
    }


def _serialize_project_item(project: Project) -> dict[str, Any]:
    leader = project.leader
    return {
        "item_type": "PROJECT",
        "public_id": str(project.public_id),
        "business_no": project.business_no,
        "title": project.name,
        "lifecycle_stage": LIFECYCLE_STAGE_PROJECT,
        "status": project.status,
        "owner_public_id": str(leader.public_id),
        "owner_display_name": leader.display_name,
        "candidate_public_id": (str(project.candidate.public_id) if project.candidate_id else None),
        "updated_at": project.updated_at.isoformat(),
    }


def _matches_filters(
    item: dict[str, Any],
    *,
    lifecycle_stage: str | None,
    status: str | None,
    owner_public_id: UUID | None,
) -> bool:
    if lifecycle_stage and item["lifecycle_stage"] != lifecycle_stage:
        return False
    if status and item["status"] != status:
        return False
    if owner_public_id and item["owner_public_id"] != str(owner_public_id):
        return False
    return True


def query_lifecycle_board(
    user: User,
    *,
    lifecycle_stage: str | None = None,
    status: str | None = None,
    owner_public_id: UUID | None = None,
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> LifecycleBoardPage:
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)

    projected_ids = _projected_opportunity_ids()
    opportunities = [item for item in list_my_opportunities(user) if item.id not in projected_ids]
    projects = _visible_projects(user)

    items = [_serialize_opportunity_item(item) for item in opportunities]
    items.extend(_serialize_project_item(item) for item in projects)
    items = [
        item
        for item in items
        if _matches_filters(
            item,
            lifecycle_stage=lifecycle_stage,
            status=status,
            owner_public_id=owner_public_id,
        )
    ]
    items.sort(
        key=lambda row: (row["updated_at"], row["item_type"], row["public_id"]),
        reverse=True,
    )

    total_count = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return LifecycleBoardPage(
        items=page_items,
        page=page,
        page_size=page_size,
        total_count=total_count,
        has_more=end < total_count,
    )
