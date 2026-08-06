"""Pilot API permission surfaces hide unauthorized resources as 404."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def manager(active_user, grant_action):
    grant_action(active_user, "pilot.batch.manage", "pilot.batch")
    grant_action(active_user, "pilot.batch.read", "pilot.batch")
    grant_action(active_user, "pilot.feedback.create", "pilot.feedback")
    grant_action(active_user, "pilot.feedback.read", "pilot.feedback")
    grant_action(active_user, "pilot.feedback.assign", "pilot.feedback")
    grant_action(active_user, "pilot.feedback.handle", "pilot.feedback")
    grant_action(active_user, "pilot.feedback.retest", "pilot.feedback")
    grant_action(active_user, "pilot.feedback.close", "pilot.feedback")
    return active_user


def test_create_batch_and_list(client, manager, another_active_user, grant_action):
    grant_action(another_active_user, "pilot.batch.read", "pilot.batch")
    client.force_login(manager)
    created = client.post(
        "/api/v1/pilot/batches",
        {"name": "API batch", "planned_participant_count": 2},
        format="json",
    )
    assert created.status_code == 201
    public_id = created.json()["public_id"]

    add = client.post(
        f"/api/v1/pilot/batches/{public_id}/participants",
        {"user_public_id": str(another_active_user.public_id), "department_snapshot": "QA"},
        format="json",
    )
    assert add.status_code == 201

    start = client.post(f"/api/v1/pilot/batches/{public_id}/start", format="json")
    assert start.status_code == 200
    assert start.json()["status"] == "OPEN"

    feedback = client.post(
        f"/api/v1/pilot/batches/{public_id}/feedback",
        {
            "title": "UI glitch",
            "reproduction_summary": "Open batch page",
            "external_key": "api-1",
        },
        format="json",
    )
    assert feedback.status_code == 201

    client.force_login(another_active_user)
    listed = client.get("/api/v1/pilot/batches")
    assert listed.status_code == 200
    assert any(item["public_id"] == public_id for item in listed.json()["items"])


def test_unprivileged_user_sees_404(client, another_active_user):
    # another_active_user does not receive the package autouse pilot grants.
    client.force_login(another_active_user)
    response = client.get("/api/v1/pilot/batches")
    assert response.status_code == 404
