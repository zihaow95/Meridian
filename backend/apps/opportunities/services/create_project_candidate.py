"""Create the initial project candidate when a proposal is approved into case.

This runs inside the major stage gate decision transaction, so it never opens or
commits its own outer transaction; it only appends to the same unit of work.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.identity.models.user import User
from apps.opportunities.models import (
    CandidateSource,
    CandidateStatus,
    CandidateType,
    CaseAssessment,
    InitialType,
    Opportunity,
    ProjectCandidate,
    SourceRole,
)
from apps.opportunities.models.assessment import (
    CORE_ASSESSMENT_CATEGORIES,
    AssessmentStatus,
)

_CANDIDATE_TYPE_BY_INITIAL = {
    InitialType.NEW: CandidateType.NEW_PRODUCT,
    InitialType.ITERATION: CandidateType.PRODUCT_CHANGE,
    InitialType.UNDECIDED: CandidateType.NEW_PRODUCT,
}


def build_candidate_from_opportunity(
    *,
    opportunity: Opportunity,
    actor: User,
    now: datetime,
    name: str | None = None,
    source_role: str = SourceRole.PRIMARY,
) -> ProjectCandidate:
    """Create a candidate, its source link and the eight seeded assessments.

    This does not append an audit event; callers own the audit trail so the
    action code matches the business command (create vs split).
    """

    candidate = ProjectCandidate.objects.create(
        organization=opportunity.organization,
        business_no=f"PC-{uuid.uuid4().hex[:8].upper()}",
        name=name or opportunity.title,
        candidate_type=_CANDIDATE_TYPE_BY_INITIAL.get(
            InitialType(opportunity.initial_type), CandidateType.NEW_PRODUCT
        ),
        status=CandidateStatus.AWAITING_ASSIGNMENT,
    )
    CandidateSource.objects.create(
        organization=opportunity.organization,
        candidate=candidate,
        opportunity=opportunity,
        source_role=source_role,
        is_active=True,
        linked_at=now,
        linked_by=actor,
    )
    CaseAssessment.objects.bulk_create(
        [
            CaseAssessment(
                organization=opportunity.organization,
                candidate=candidate,
                category_code=category,
                status=AssessmentStatus.NOT_STARTED,
            )
            for category in CORE_ASSESSMENT_CATEGORIES
        ]
    )
    return candidate


def create_initial_candidate(
    *,
    opportunity: Opportunity,
    actor: User,
    now: datetime,
    trace_id: str,
) -> ProjectCandidate:
    candidate = build_candidate_from_opportunity(opportunity=opportunity, actor=actor, now=now)

    append_event(
        AuditRecord(
            actor=actor,
            action_code="candidate.create",
            resource_type="project_candidate",
            resource_public_id=candidate.public_id,
            result=AuditResult.SUCCESS,
            trace_id=trace_id,
            occurred_at=now,
            acting_roles_snapshot=acting_roles_snapshot(actor),
            after_summary={
                "status": candidate.status,
                "opportunity": str(opportunity.public_id),
            },
        )
    )
    return candidate
