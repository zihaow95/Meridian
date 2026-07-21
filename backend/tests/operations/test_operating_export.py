"""Operating data export permission and ticket issuance."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User


@pytest.mark.django_db(transaction=True)
def test_export_requires_operating_detail_export(
    api_client: APIClient,
    active_user: User,
    grant_action,
) -> None:
    grant_action(active_user, "operating_fact.read", "operating_fact")
    api_client.force_authenticate(user=active_user)

    denied = api_client.post(
        "/api/v1/operating-data/exports",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_granularity": "QUARTER",
        },
        format="json",
    )
    assert denied.status_code == 404
    assert denied.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db(transaction=True)
def test_export_returns_download_token(
    api_client: APIClient,
    active_user: User,
    grant_action,
) -> None:
    grant_action(active_user, "operating_detail.export", "operating_fact")
    api_client.force_authenticate(user=active_user)

    response = api_client.post(
        "/api/v1/operating-data/exports",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_granularity": "QUARTER",
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["document_version_public_id"]
    assert body["expires_at"]
