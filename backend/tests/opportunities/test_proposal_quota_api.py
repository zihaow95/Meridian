"""Proposal quota read API."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.platform.application.command import CommandContext


@pytest.fixture
def proposer(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    grant_action(active_user, "opportunity.submit", "opportunity", role_code="PROPOSER")
    return active_user


@pytest.mark.django_db
def test_current_quota_endpoint_returns_user_counts(
    api_client: APIClient, proposer: User, opportunity_rules
) -> None:
    api_client.force_authenticate(user=proposer)
    response = api_client.get("/api/v1/proposal-quotas/current")
    assert response.status_code == 200
    body = response.json()
    assert body["owner_type"] == "USER"
    assert body["owner_public_id"] == str(proposer.public_id)
    assert body["counted_submissions"] == 0
    assert body["minimum_count"] == 3
    assert body["enforcement_mode"] == "WARN"
    assert body["is_below_minimum"] is True
    assert body["deficit"] == 3


@pytest.mark.django_db
def test_current_quota_reflects_submitted_proposal(
    api_client: APIClient, proposer: User, opportunity_rules
) -> None:
    opportunity = CreateOpportunityDraft(
        context=CommandContext.for_actor(proposer),
        title="Quota yogurt",
        public_summary="summary",
        market_analysis="market",
        core_selling_points="points",
        target_users_needs="needs",
        suggested_retail_price=Decimal("9.90"),
    ).execute()
    SubmitProposal(
        context=CommandContext.for_actor(proposer),
        opportunity_public_id=opportunity.public_id,
        version_no=opportunity.version_no,
        idempotency_key="quota-submit",
    ).execute()

    api_client.force_authenticate(user=proposer)
    response = api_client.get("/api/v1/proposal-quotas/current")
    assert response.status_code == 200
    assert response.json()["counted_submissions"] == 1
    assert response.json()["deficit"] == 2
