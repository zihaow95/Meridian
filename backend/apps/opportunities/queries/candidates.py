"""Read serialization for project candidates."""

from __future__ import annotations

from typing import Any

from apps.opportunities.models import CaseAssessment, ProjectCandidate


def serialize_assessment(assessment: CaseAssessment) -> dict[str, Any]:
    return {
        "category_code": assessment.category_code,
        "status": assessment.status,
        "conclusion": assessment.conclusion,
        "deliverable_version_public_id": (
            str(assessment.deliverable_version_public_id)
            if assessment.deliverable_version_public_id
            else None
        ),
    }


def serialize_candidate_detail(candidate: ProjectCandidate) -> dict[str, Any]:
    case_owner = candidate.case_owner
    deputy_leader = candidate.deputy_leader
    return {
        "public_id": str(candidate.public_id),
        "business_no": candidate.business_no,
        "name": candidate.name,
        "candidate_type": candidate.candidate_type,
        "status": candidate.status,
        "version_no": candidate.version_no,
        "case_owner_public_id": (str(case_owner.public_id) if case_owner else None),
        "deputy_leader_public_id": (str(deputy_leader.public_id) if deputy_leader else None),
        "proposed_schedule": candidate.proposed_schedule,
        "resource_risk_summary": candidate.resource_risk_summary,
        "assessments": [
            serialize_assessment(item)
            for item in candidate.assessments.all().order_by("category_code")
        ],
    }
