"""HTTP surface for drafting, requesting and reviewing a configuration publication.

Until phase 6 the AdminChangeRequest state machine had no HTTP entry at all, so
dual control existed in code but was unreachable from the product. These tests
pin the reachable path, including the parts a reviewer needs: seeing what is
pending, and being refused when the request is their own.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.authorization.models.admin_change import AdminChangeStatus
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import TECHNICAL_FILE_CATALOG_CODE

DRAFTS_URL = "/api/v1/configurations/definitions/{code}/drafts"
VERSION_URL = "/api/v1/configurations/versions/{public_id}"
REQUEST_URL = "/api/v1/configurations/versions/{public_id}/publication-requests"
PENDING_URL = "/api/v1/configurations/publication-requests"
REVIEW_URL = "/api/v1/configurations/publication-requests/{public_id}/review"
PUBLISH_URL = "/api/v1/configurations/versions/{public_id}/publish"


def catalog_content() -> dict[str, Any]:
    return {
        "catalog_items": [
            {
                "item_code": "PRODUCT_SPEC",
                "name": "Product specification",
                "allowed_mime_types": ["application/pdf"],
                "max_bytes": 52_428_800,
                "preview_enabled": True,
                "default_sensitivity_level": "SENSITIVE_CONTROLLED",
                "retention_years": 5,
            }
        ]
    }


@pytest.fixture
def catalog_definition(organization) -> ConfigurationDefinition:
    return ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=TECHNICAL_FILE_CATALOG_CODE,
        name="Technical file catalog",
    )


def post_json(client: Client, url: str, payload: dict[str, Any] | None = None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


@pytest.mark.django_db
def test_creating_a_draft_requires_the_draft_action(
    client: Client, active_user, catalog_definition
) -> None:
    client.force_login(active_user)

    response = post_json(
        client,
        DRAFTS_URL.format(code=TECHNICAL_FILE_CATALOG_CODE),
        {"content": catalog_content()},
    )

    assert response.status_code == 404
    assert ConfigurationVersion.objects.filter(definition=catalog_definition).count() == 0


@pytest.mark.django_db
def test_author_creates_a_draft_that_starts_unpublished(
    client: Client, active_user, grant_action, catalog_definition
) -> None:
    grant_action(active_user, "configuration.draft.create", "configuration.version")
    client.force_login(active_user)

    response = post_json(
        client,
        DRAFTS_URL.format(code=TECHNICAL_FILE_CATALOG_CODE),
        {"content": catalog_content()},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ConfigurationStatus.DRAFT
    assert body["version_number"] == 1
    version = ConfigurationVersion.objects.get(public_id=body["public_id"])
    assert version.current_published_slot is None


@pytest.mark.django_db
def test_draft_content_that_fails_its_schema_is_reported_as_validation_errors(
    client: Client, active_user, grant_action, catalog_definition
) -> None:
    grant_action(active_user, "configuration.draft.create", "configuration.version")
    client.force_login(active_user)
    broken = catalog_content()
    broken["catalog_items"][0]["default_sensitivity_level"] = "TOP_SECRET"

    response = post_json(
        client, DRAFTS_URL.format(code=TECHNICAL_FILE_CATALOG_CODE), {"content": broken}
    )

    assert response.status_code == 400
    assert ConfigurationVersion.objects.filter(definition=catalog_definition).count() == 0


@pytest.mark.django_db
def test_version_detail_withholds_content_without_the_sensitive_read_action(
    client: Client, active_user, grant_action, catalog_definition, draft_of
) -> None:
    grant_action(active_user, "configuration.version.read", "configuration.version")
    draft = draft_of(catalog_definition)
    client.force_login(active_user)

    response = client.get(VERSION_URL.format(public_id=draft.public_id))

    assert response.status_code == 200
    assert response.json()["content_json"] is None


@pytest.mark.django_db
def test_version_detail_returns_content_with_the_sensitive_read_action(
    client: Client, active_user, grant_action, catalog_definition, draft_of
) -> None:
    grant_action(active_user, "configuration.version.read", "configuration.version")
    grant_action(active_user, "configuration.content.read_sensitive", "configuration.version")
    draft = draft_of(catalog_definition)
    client.force_login(active_user)

    response = client.get(VERSION_URL.format(public_id=draft.public_id))

    assert response.status_code == 200
    assert response.json()["content_json"] == catalog_content()


@pytest.mark.django_db
def test_requesting_publication_puts_the_version_in_the_pending_queue(
    client: Client, active_user, grant_action, catalog_definition, draft_of
) -> None:
    grant_action(active_user, "configuration.publication.request", "configuration.version")
    grant_action(active_user, "configuration.version.read", "configuration.version")
    draft = draft_of(catalog_definition)
    client.force_login(active_user)

    created = post_json(client, REQUEST_URL.format(public_id=draft.public_id))
    listed = client.get(PENDING_URL)

    assert created.status_code == 201
    assert created.json()["status"] == AdminChangeStatus.PENDING
    pending = listed.json()
    assert [row["public_id"] for row in pending] == [created.json()["public_id"]]
    assert pending[0]["definition_code"] == TECHNICAL_FILE_CATALOG_CODE


@pytest.mark.django_db
def test_reviewer_cannot_approve_their_own_publication_request(
    client: Client, active_user, grant_action, catalog_definition, draft_of
) -> None:
    grant_action(active_user, "configuration.publication.request", "configuration.version")
    grant_action(active_user, "configuration.publication.review", "configuration.version")
    draft = draft_of(catalog_definition)
    client.force_login(active_user)
    created = post_json(client, REQUEST_URL.format(public_id=draft.public_id))

    response = post_json(
        client,
        REVIEW_URL.format(public_id=created.json()["public_id"]),
        {"decision": AdminChangeStatus.APPROVED},
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_publish_is_refused_while_no_approval_exists(
    client: Client, active_user, grant_action, catalog_definition, draft_of
) -> None:
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    draft = draft_of(catalog_definition)
    client.force_login(active_user)

    response = post_json(client, PUBLISH_URL.format(public_id=draft.public_id))

    assert response.status_code == 409
    draft.refresh_from_db()
    assert draft.status == ConfigurationStatus.DRAFT


@pytest.mark.django_db
def test_approved_request_lets_the_publisher_publish_once(
    client: Client,
    active_user,
    another_active_user,
    grant_action,
    catalog_definition,
    draft_of,
) -> None:
    grant_action(active_user, "configuration.publication.request", "configuration.version")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    grant_action(another_active_user, "configuration.publication.review", "configuration.version")
    draft = draft_of(catalog_definition)

    client.force_login(active_user)
    created = post_json(client, REQUEST_URL.format(public_id=draft.public_id))
    client.force_login(another_active_user)
    reviewed = post_json(
        client,
        REVIEW_URL.format(public_id=created.json()["public_id"]),
        {"decision": AdminChangeStatus.APPROVED},
    )
    client.force_login(active_user)
    published = post_json(client, PUBLISH_URL.format(public_id=draft.public_id))
    replay = post_json(client, PUBLISH_URL.format(public_id=draft.public_id))

    assert reviewed.json()["status"] == AdminChangeStatus.APPROVED
    assert published.status_code == 200
    assert published.json()["status"] == ConfigurationStatus.PUBLISHED
    assert replay.status_code == 409


@pytest.mark.django_db
def test_rejected_request_leaves_the_version_unpublished(
    client: Client,
    active_user,
    another_active_user,
    grant_action,
    catalog_definition,
    draft_of,
) -> None:
    grant_action(active_user, "configuration.publication.request", "configuration.version")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    grant_action(another_active_user, "configuration.publication.review", "configuration.version")
    draft = draft_of(catalog_definition)

    client.force_login(active_user)
    created = post_json(client, REQUEST_URL.format(public_id=draft.public_id))
    client.force_login(another_active_user)
    post_json(
        client,
        REVIEW_URL.format(public_id=created.json()["public_id"]),
        {"decision": AdminChangeStatus.REJECTED},
    )
    client.force_login(active_user)
    response = post_json(client, PUBLISH_URL.format(public_id=draft.public_id))

    assert response.status_code == 409
    draft.refresh_from_db()
    assert draft.status == ConfigurationStatus.DRAFT
