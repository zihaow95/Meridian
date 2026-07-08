"""Submitting a project candidate opens the CASE_TO_PROJECT major gate."""

from __future__ import annotations

import pytest

from apps.configuration.models import ConfigurationVersion
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.errors import CaseAssessmentIncomplete
from apps.opportunities.models import (
    AssessmentStatus,
    CandidateStatus,
    CaseAssessment,
    ProjectCandidate,
)
from apps.opportunities.models.assessment import CORE_ASSESSMENT_CATEGORIES
from apps.opportunities.services.submit_project_review import SubmitProjectReview
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import (
    GateStatus,
    StageCode,
    StageGateInstance,
    SubjectType,
)


def _assessing_candidate(
    organization: Organization,
    case_owner: User,
    *,
    confirmed: set[str],
) -> ProjectCandidate:
    candidate = ProjectCandidate.objects.create(
        organization=organization,
        business_no="PC-REVIEW",
        name="Candidate",
        status=CandidateStatus.ASSESSING,
        case_owner=case_owner,
        resource_risk_summary="Supply risk is mitigated by dual sourcing.",
        proposed_schedule={"launch": "2026Q4"},
    )
    CaseAssessment.objects.bulk_create(
        [
            CaseAssessment(
                organization=organization,
                candidate=candidate,
                category_code=category,
                status=(
                    AssessmentStatus.CONFIRMED
                    if category in confirmed
                    else AssessmentStatus.NOT_STARTED
                ),
            )
            for category in CORE_ASSESSMENT_CATEGORIES
        ]
    )
    return candidate


@pytest.mark.django_db
def test_submit_project_review_requires_all_core_assessments(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    confirmed = {c for c in CORE_ASSESSMENT_CATEGORIES if c != "COST"}
    candidate = _assessing_candidate(organization, product_manager, confirmed=confirmed)

    with pytest.raises(CaseAssessmentIncomplete) as exc:
        SubmitProjectReview(
            context=CommandContext.for_actor(product_director),
            candidate_public_id=candidate.public_id,
            version_no=candidate.version_no,
            idempotency_key="project-review-1",
        ).execute()

    assert "COST" in exc.value.missing_categories
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.ASSESSING


@pytest.mark.django_db
def test_submit_project_review_opens_case_gate(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    confirmed = set(CORE_ASSESSMENT_CATEGORIES)
    candidate = _assessing_candidate(organization, product_manager, confirmed=confirmed)

    result = SubmitProjectReview(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        idempotency_key="project-review-1",
    ).execute()

    assert result.status == CandidateStatus.IN_PROJECT_REVIEW
    gate = StageGateInstance.objects.get(
        subject_type=SubjectType.PROJECT_CANDIDATE,
        subject_public_id=candidate.public_id,
        stage_code=StageCode.CASE_TO_PROJECT,
    )
    assert gate.status == GateStatus.OPEN


@pytest.mark.django_db
def test_submit_project_review_is_idempotent(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> None:
    confirmed = set(CORE_ASSESSMENT_CATEGORIES)
    candidate = _assessing_candidate(organization, product_manager, confirmed=confirmed)
    ctx = CommandContext.for_actor(product_director)

    first = SubmitProjectReview(
        context=ctx,
        candidate_public_id=candidate.public_id,
        version_no=candidate.version_no,
        idempotency_key="project-review-1",
    ).execute()
    # A second call once already in review is a no-op returning the same subject.
    second = SubmitProjectReview(
        context=CommandContext.for_actor(product_director),
        candidate_public_id=candidate.public_id,
        version_no=first.version_no,
        idempotency_key="project-review-2",
    ).execute()

    assert second.status == CandidateStatus.IN_PROJECT_REVIEW
    assert (
        StageGateInstance.objects.filter(
            subject_type=SubjectType.PROJECT_CANDIDATE,
            subject_public_id=candidate.public_id,
            stage_code=StageCode.CASE_TO_PROJECT,
        ).count()
        == 1
    )
