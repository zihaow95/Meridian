"""Phase 2 acceptance: proposal through project creation and lifecycle board."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.test import Client

from apps.identity.models.user import User
from apps.opportunities.models import AssessmentStatus, CandidateStatus, ProposalStatus
from apps.opportunities.models.assessment import CORE_ASSESSMENT_CATEGORIES
from apps.projects.models import Project


@pytest.fixture
def phase2_configuration(opportunity_rules, project_template_version):  # noqa: ANN001
    del project_template_version
    return opportunity_rules


@pytest.fixture
def phase2_product_manager(
    product_manager: User,
    grant_action: Callable[..., None],
) -> User:
    grant_action(product_manager, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(product_manager, "opportunity.submit", "opportunity", role_code="PROPOSER")
    grant_action(product_manager, "opportunity.edit", "opportunity", role_code="PROPOSER")
    grant_action(
        product_manager,
        "candidate.leadership.assign",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    grant_action(
        product_manager,
        "candidate.assessment.edit",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    grant_action(
        product_manager,
        "candidate.submit_review",
        "project_candidate",
        role_code="PRODUCT_DIRECTOR",
    )
    return product_manager


@pytest.fixture
def phase2_boss(boss: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        boss,
        "major_gate.management_conclusion.record",
        "stage_gate",
        role_code="BOSS",
    )
    return boss


@pytest.mark.django_db(transaction=True)
def test_product_manager_can_submit_review_and_create_project(
    client: Client,
    phase2_product_manager: User,
    phase2_boss: User,
    phase2_configuration,  # noqa: ANN001, ARG001
) -> None:
    client.force_login(phase2_product_manager)
    create_response = client.post(
        "/api/v1/opportunities",
        data={
            "title": "High protein yogurt",
            "initial_type": "NEW",
            "public_summary": "Breakfast protein yogurt",
            "market_analysis": "Demand exists in convenience channels.",
            "core_selling_points": "High protein and low sugar.",
            "target_users_needs": "Breakfast replacement.",
            "suggested_retail_price": "9.90",
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    opportunity = create_response.json()
    opportunity_id = opportunity["public_id"]
    version_no = opportunity["version_no"]

    submit_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/submit",
        data={"version_no": version_no, "idempotency_key": "submit-e2e"},
        content_type="application/json",
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["proposal_status"] == ProposalStatus.SUBMITTED

    client.force_login(phase2_boss)
    review_response = client.post(
        f"/api/v1/opportunities/{opportunity_id}/review-cycles",
        data={},
        content_type="application/json",
    )
    assert review_response.status_code == 201
    proposal_gate_id = review_response.json()["public_id"]

    proposal_decision_response = client.post(
        f"/api/v1/stage-gates/{proposal_gate_id}/major-decision",
        data={
            "management_conclusion": "APPROVED",
            "final_decision": "APPROVED",
            "decision_summary": "Enter case.",
            "idempotency_key": "proposal-gate",
        },
        content_type="application/json",
    )
    assert proposal_decision_response.status_code == 201

    client.force_login(phase2_product_manager)
    board_after_case = client.get("/api/v1/lifecycle-board")
    assert board_after_case.status_code == 200
    case_items = [
        item
        for item in board_after_case.json()["items"]
        if item["public_id"] == opportunity_id and item["lifecycle_stage"] == "CASE"
    ]
    assert len(case_items) == 1
    candidate_public_id = case_items[0]["candidate_public_id"]
    assert candidate_public_id is not None

    leadership_response = client.post(
        f"/api/v1/project-candidates/{candidate_public_id}/leadership",
        data={
            "version_no": 1,
            "case_owner_public_id": str(phase2_product_manager.public_id),
        },
        content_type="application/json",
    )
    assert leadership_response.status_code == 200
    candidate_version_no = leadership_response.json()["version_no"]

    for category in CORE_ASSESSMENT_CATEGORIES:
        assessment_response = client.patch(
            f"/api/v1/project-candidates/{candidate_public_id}/assessments/{category}",
            data={"status": AssessmentStatus.CONFIRMED, "conclusion": "Ready."},
            content_type="application/json",
        )
        assert assessment_response.status_code == 200

    submit_review_response = client.post(
        f"/api/v1/project-candidates/{candidate_public_id}/submit-review",
        data={
            "version_no": candidate_version_no,
            "idempotency_key": "candidate-review",
            "resource_risk_summary": "Supply risk is mitigated.",
            "proposed_schedule": {"launch": "2026Q4"},
        },
        content_type="application/json",
    )
    assert submit_review_response.status_code == 200
    assert submit_review_response.json()["status"] == CandidateStatus.IN_PROJECT_REVIEW
    project_gate_id = submit_review_response.json()["active_stage_gate_public_id"]
    assert project_gate_id is not None

    client.force_login(phase2_boss)
    project_decision_response = client.post(
        f"/api/v1/stage-gates/{project_gate_id}/major-decision",
        data={
            "management_conclusion": "APPROVED",
            "final_decision": "APPROVED",
            "decision_summary": "Create project.",
            "idempotency_key": "project-gate",
        },
        content_type="application/json",
    )
    assert project_decision_response.status_code == 201

    project = Project.objects.get(candidate__public_id=candidate_public_id)
    assert project.leader_id == phase2_product_manager.id

    client.force_login(phase2_product_manager)
    board_response = client.get("/api/v1/lifecycle-board")
    assert board_response.status_code == 200
    board_items = board_response.json()["items"]
    project_items = [item for item in board_items if item["item_type"] == "PROJECT"]
    assert any(item["public_id"] == str(project.public_id) for item in project_items)
    assert not any(item["public_id"] == opportunity_id for item in board_items)
