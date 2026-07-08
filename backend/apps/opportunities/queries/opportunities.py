"""Read models for opportunities filtered by the caller's relationship."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.identity.models.user import User
from apps.opportunities.models import (
    InvitationStatus,
    Opportunity,
    OpportunityMember,
    ProposalVersion,
)


def list_my_opportunities(user: User) -> list[Opportunity]:
    now = timezone.now()
    member_opportunity_ids = (
        OpportunityMember.objects.filter(
            user=user,
            invitation_status=InvitationStatus.ACCEPTED,
            active_from__lte=now,
        )
        .filter(Q(active_to__isnull=True) | Q(active_to__gt=now))
        .values_list("opportunity_id", flat=True)
    )
    return list(
        Opportunity.objects.filter(organization_id=user.organization_id)
        .filter(Q(proposal_owner=user) | Q(id__in=member_opportunity_ids))
        .order_by("-updated_at")
    )


def serialize_summary(opportunity: Opportunity) -> dict[str, Any]:
    return {
        "public_id": str(opportunity.public_id),
        "business_no": opportunity.business_no,
        "title": opportunity.title,
        "public_summary": opportunity.public_summary,
        "initial_type": opportunity.initial_type,
        "proposal_status": opportunity.proposal_status,
        "version_no": opportunity.version_no,
        "updated_at": opportunity.updated_at.isoformat(),
    }


def serialize_public(opportunity: Opportunity) -> dict[str, Any]:
    return {
        "public_id": str(opportunity.public_id),
        "title": opportunity.title,
        "public_summary": opportunity.public_summary,
        "proposal_status": opportunity.proposal_status,
    }


def serialize_detail(opportunity: Opportunity) -> dict[str, Any]:
    version = opportunity.current_version
    detail = serialize_summary(opportunity)
    detail["quota_owner_type"] = opportunity.quota_owner_type
    detail["current_version"] = _serialize_version(version) if version else None
    return detail


def list_versions(opportunity: Opportunity) -> list[dict[str, Any]]:
    versions = ProposalVersion.objects.filter(opportunity=opportunity).order_by("version_number")
    return [_serialize_version(version) for version in versions]


def _serialize_version(version: ProposalVersion) -> dict[str, Any]:
    return {
        "public_id": str(version.public_id),
        "version_number": version.version_number,
        "version_status": version.version_status,
        "market_analysis": version.market_analysis,
        "core_selling_points": version.core_selling_points,
        "target_users_needs": version.target_users_needs,
        "suggested_retail_price": (
            str(version.suggested_retail_price)
            if version.suggested_retail_price is not None
            else None
        ),
        "submitted_at": (version.submitted_at.isoformat() if version.submitted_at else None),
        "locked_at": version.locked_at.isoformat() if version.locked_at else None,
    }
