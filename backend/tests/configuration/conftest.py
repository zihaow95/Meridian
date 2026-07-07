"""Configuration test fixtures."""

from __future__ import annotations

import pytest

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import FILE_UPLOAD_DEFINITION_CODE
from apps.configuration.services import CreateDraft, PublishVersion
from apps.identity.models.organization import Organization
from apps.identity.models.user import User


@pytest.fixture
def file_upload_definition(organization: Organization) -> ConfigurationDefinition:
    return ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=FILE_UPLOAD_DEFINITION_CODE,
        name="File upload policy",
    )


@pytest.fixture
def draft_version(
    file_upload_definition: ConfigurationDefinition, active_user: User
) -> ConfigurationVersion:
    return CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 10_485_760},
    ).execute()


@pytest.fixture
def published_version(
    draft_version: ConfigurationVersion, active_user: User
) -> ConfigurationVersion:
    return PublishVersion(version=draft_version, actor=active_user).execute()
