"""API coverage for migration batch import and confirm."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models.user import User, UserStatus
from apps.projects.models import MigrationDisposition


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def migrator(organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="API Migrator",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "project_migration.confirm", "project", role_code="PRODUCT_DIRECTOR")
    return user


@pytest.mark.django_db
def test_migration_batch_api_import_and_archive(
    api_client: APIClient,
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    api_client.force_authenticate(user=migrator)
    create = api_client.post(
        "/api/v1/project-migration-batches",
        {
            "batch_key": "api-batch-1",
            "rows": [
                {
                    "external_project_id": "API-EXT-1",
                    "name": "Archived legacy",
                    "current_stage_code": "D3",
                    "disposition": MigrationDisposition.ARCHIVE_ONLY,
                    "history_decision_summary": "offline",
                    "history_tasks": [],
                    "history_files": [],
                }
            ],
        },
        format="json",
    )
    assert create.status_code == 201
    baseline_id = create.data["baselines"][0]["public_id"]
    confirm = api_client.post(
        f"/api/v1/project-migration-baselines/{baseline_id}/confirm",
        {
            "disposition": MigrationDisposition.ARCHIVE_ONLY,
            "idempotency_key": "api-confirm-1",
        },
        format="json",
    )
    assert confirm.status_code == 200
    assert confirm.data["project_public_id"] is None
    assert confirm.data["disposition"] == MigrationDisposition.ARCHIVE_ONLY
