"""Read models for operating issues."""

from __future__ import annotations

from uuid import UUID

from apps.operations.models import IssueDecision, IssueSignal, OperatingIssue
from apps.platform.api.errors import PermissionDeniedError


def get_operating_issue(*, organization_id: int, issue_public_id: UUID) -> dict:
    issue = (
        OperatingIssue.objects.select_related("product", "owner", "data_snapshot")
        .filter(organization_id=organization_id, public_id=issue_public_id)
        .first()
    )
    if issue is None:
        raise PermissionDeniedError()
    links = list(
        IssueSignal.objects.filter(issue=issue)
        .select_related("signal")
        .order_by("-is_primary", "linked_at")
    )
    decisions = list(
        IssueDecision.objects.filter(issue=issue).order_by("-decided_at", "-id")
    )
    return {
        "public_id": str(issue.public_id),
        "business_no": issue.business_no,
        "title": issue.title,
        "status": issue.status,
        "version_no": issue.version_no,
        "source_type": issue.source_type,
        "phenomenon_summary": issue.phenomenon_summary,
        "recommendation_type": issue.recommendation_type,
        "product_public_id": str(issue.product.public_id),
        "owner_public_id": str(issue.owner.public_id),
        "data_snapshot_public_id": (
            str(issue.data_snapshot.public_id) if issue.data_snapshot_id else None
        ),
        "target_review_at": (
            issue.target_review_at.isoformat() if issue.target_review_at else None
        ),
        "signals": [
            {
                "signal_public_id": str(link.signal.public_id),
                "is_primary": link.is_primary,
                "active_primary_slot": link.active_primary_slot,
                "unlinked_at": link.unlinked_at.isoformat() if link.unlinked_at else None,
            }
            for link in links
        ],
        "decisions": [
            {
                "public_id": str(row.public_id),
                "recommendation_type": row.recommendation_type,
                "action_summary": row.action_summary,
                "decided_at": row.decided_at.isoformat(),
            }
            for row in decisions
        ],
    }
