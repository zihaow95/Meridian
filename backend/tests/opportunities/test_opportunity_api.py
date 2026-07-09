"""Opportunity API contract: unified errors, no primary key leakage."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.opportunities.models import Opportunity, ProposalStatus


@pytest.fixture
def proposer(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(active_user, "opportunity.submit", "opportunity", role_code="PROPOSER")
    return active_user


def _create_payload() -> dict[str, object]:
    return {
        "title": "High protein yogurt",
        "initial_type": "NEW",
        "public_summary": "Breakfast protein yogurt",
        "market_analysis": "Demand exists in convenience channels.",
        "core_selling_points": "High protein and low sugar.",
        "target_users_needs": "Breakfast replacement.",
        "suggested_retail_price": "9.90",
    }


@pytest.mark.django_db
def test_create_then_get_opportunity(api_client: APIClient, proposer: User) -> None:
    api_client.force_authenticate(user=proposer)
    create = api_client.post("/api/v1/opportunities", _create_payload(), format="json")
    assert create.status_code == 201
    public_id = create.json()["public_id"]

    detail = api_client.get(f"/api/v1/opportunities/{public_id}")
    assert detail.status_code == 200
    assert detail.json()["proposal_status"] == ProposalStatus.DRAFT
    assert detail.json()["current_version"]["market_analysis"]


@pytest.mark.django_db
def test_create_without_eligibility_is_hidden(api_client: APIClient, active_user: User) -> None:
    api_client.force_authenticate(user=active_user)
    response = api_client.post("/api/v1/opportunities", _create_payload(), format="json")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db
def test_submit_without_eligibility_returns_error_contract(
    api_client: APIClient,
    another_active_user: User,
    organization,
) -> None:
    # another_active_user owns a draft but holds no proposer grant.
    opportunity = Opportunity.objects.create(
        organization=organization,
        business_no="OPP-CONTRACT",
        title="Draft",
        public_summary="summary",
        proposal_owner=another_active_user,
        quota_owner_type="USER",
        quota_owner_id=another_active_user.id,
        proposal_status=ProposalStatus.DRAFT,
    )
    api_client.force_authenticate(user=another_active_user)
    response = api_client.post(
        f"/api/v1/opportunities/{opportunity.public_id}/submit",
        {"version_no": opportunity.version_no, "idempotency_key": "s1"},
        format="json",
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "PROPOSAL_SUBMITTER_NOT_ELIGIBLE"
    assert "trace_id" in body
    # Unified error contract must not leak the internal primary key.
    assert set(body.keys()) == {"code", "message", "details", "trace_id"}
    assert "id" not in body


@pytest.mark.django_db
def test_versions_endpoint_lists_versions(api_client: APIClient, proposer: User) -> None:
    api_client.force_authenticate(user=proposer)
    create = api_client.post("/api/v1/opportunities", _create_payload(), format="json")
    public_id = create.json()["public_id"]
    response = api_client.get(f"/api/v1/opportunities/{public_id}/versions")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["version_number"] == 1
