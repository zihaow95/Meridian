"""Configuration API rules."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.configuration.models import ConfigurationStatus


@pytest.mark.django_db
def test_configuration_definitions_requires_read_permission(
    client: Client, active_user, file_upload_definition
) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/configurations/definitions")
    assert response.status_code == 404


@pytest.mark.django_db
def test_configuration_reader_can_list_definitions(
    client: Client, active_user, grant_action, file_upload_definition
) -> None:
    grant_action(active_user, "configuration.version.read", "configuration.version")
    client.force_login(active_user)
    response = client.get("/api/v1/configurations/definitions")
    assert response.status_code == 200
    codes = [row["definition_code"] for row in response.json()]
    assert file_upload_definition.definition_code in codes


@pytest.mark.django_db
def test_configuration_publisher_can_publish_draft(
    client: Client, active_user, grant_action, draft_version
) -> None:
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    client.force_login(active_user)
    response = client.post(f"/api/v1/configurations/versions/{draft_version.public_id}/publish")
    assert response.status_code == 200
    draft_version.refresh_from_db()
    assert draft_version.status == ConfigurationStatus.PUBLISHED
