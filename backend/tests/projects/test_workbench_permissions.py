"""Project workbench list/detail permission filtering (Task 4.8)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models.user import User, UserStatus
from apps.projects.models import Project
from tests.stage_gates.first_launch_fixtures import prepare_submitted_first_launch_gate


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def outsider(organization) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Outsider",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


@pytest.mark.django_db
def test_project_list_hides_projects_from_non_members(
    api_client: APIClient,
    project: Project,
    outsider: User,
) -> None:
    api_client.force_authenticate(user=outsider)
    response = api_client.get("/api/v1/projects")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert all(row["public_id"] != str(project.public_id) for row in body["items"])


@pytest.mark.django_db
def test_project_detail_hides_existence_for_non_members(
    api_client: APIClient,
    project: Project,
    outsider: User,
) -> None:
    api_client.force_authenticate(user=outsider)
    response = api_client.get(f"/api/v1/projects/{project.public_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db
def test_project_leader_can_list_and_read_stages(
    api_client: APIClient,
    project: Project,
) -> None:
    api_client.force_authenticate(user=project.leader)
    listed = api_client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    assert any(row["public_id"] == str(project.public_id) for row in listed.json()["items"])

    stages = api_client.get(f"/api/v1/projects/{project.public_id}/stages")
    assert stages.status_code == 200
    codes = {row["stage_code"] for row in stages.json()["items"]}
    assert "D1" in codes
    assert "L2" in codes


@pytest.mark.django_db
def test_task_list_requires_project_visibility(
    api_client: APIClient,
    project: Project,
    outsider: User,
) -> None:
    api_client.force_authenticate(user=outsider)
    response = api_client.get(f"/api/v1/projects/{project.public_id}/tasks")
    assert response.status_code == 404


@pytest.mark.django_db
def test_workbench_detail_launch_capabilities_reflect_management_only_actor(
    api_client: APIClient,
    project: Project,
    grant_action: Callable[..., None],
) -> None:
    """A conclusion-only actor sees only the management action as available."""

    prepare_submitted_first_launch_gate(project)
    leader = project.leader
    grant_action(
        leader,
        "first_launch.management_conclusion.record",
        "stage_gate",
        role_code="MANAGEMENT_COMMITTEE",
    )
    api_client.force_authenticate(user=leader)

    response = api_client.get(f"/api/v1/projects/{project.public_id}")

    assert response.status_code == 200
    capabilities = response.json()["launch_capabilities"]
    assert capabilities["can_record_management_conclusion"] is True
    assert capabilities["can_record_final_decision"] is False


@pytest.mark.django_db
def test_workbench_detail_launch_capabilities_reflect_final_only_actor(
    api_client: APIClient,
    project: Project,
    grant_action: Callable[..., None],
) -> None:
    """A final-only actor sees only the final decision action as available."""

    prepare_submitted_first_launch_gate(project)
    leader = project.leader
    grant_action(
        leader,
        "first_launch.final_decision.record",
        "stage_gate",
        role_code="BOSS_FINAL",
    )
    api_client.force_authenticate(user=leader)

    response = api_client.get(f"/api/v1/projects/{project.public_id}")

    assert response.status_code == 200
    capabilities = response.json()["launch_capabilities"]
    assert capabilities["can_record_management_conclusion"] is False
    assert capabilities["can_record_final_decision"] is True
