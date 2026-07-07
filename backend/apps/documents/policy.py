"""Resolve upload policy from published configuration or settings fallback."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import FILE_UPLOAD_DEFINITION_CODE
from apps.identity.models.organization import Organization


@dataclass(frozen=True)
class UploadPolicy:
    allowed_mime_types: frozenset[str]
    max_bytes: int


def resolve_upload_policy(organization: Organization) -> UploadPolicy:
    definition = ConfigurationDefinition.objects.filter(
        organization=organization,
        definition_code=FILE_UPLOAD_DEFINITION_CODE,
    ).first()
    if definition is not None:
        published = (
            ConfigurationVersion.objects.filter(
                definition=definition,
                status=ConfigurationStatus.PUBLISHED,
            )
            .order_by("-version_number")
            .first()
        )
        if published is not None:
            content = published.content_json
            return UploadPolicy(
                allowed_mime_types=frozenset(content.get("allowed_mime_types", [])),
                max_bytes=int(content["max_bytes"]),
            )

    return UploadPolicy(
        allowed_mime_types=frozenset(
            getattr(settings, "FILE_UPLOAD_ALLOWED_MIME_TYPES", ["application/pdf"])
        ),
        max_bytes=int(getattr(settings, "FILE_UPLOAD_MAX_BYTES", 10_485_760)),
    )
