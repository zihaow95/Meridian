"""Resolve upload rules from the published technical file catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import TECHNICAL_FILE_CATALOG_CODE
from apps.identity.models.organization import Organization

# Backstop for a catalog that is wrong or maliciously large. The business limit
# comes from configuration only; this cap exists so a bad publish cannot ask the
# platform to accept an arbitrarily large file.
DEFAULT_HARD_MAX_BYTES = 209_715_200


class CatalogItemUnavailable(Exception):
    """The catalog does not authorize uploading this item right now."""


@dataclass(frozen=True)
class CatalogItemRules:
    item_code: str
    name: str
    allowed_mime_types: frozenset[str]
    max_bytes: int
    preview_enabled: bool
    default_sensitivity_level: str
    retention_years: int
    catalog_version_public_id: UUID
    catalog_content_digest: str


def hard_max_bytes() -> int:
    return int(getattr(settings, "DOCUMENT_UPLOAD_HARD_MAX_BYTES", DEFAULT_HARD_MAX_BYTES))


def published_catalog(organization: Organization) -> ConfigurationVersion:
    definition = ConfigurationDefinition.objects.filter(
        organization=organization,
        definition_code=TECHNICAL_FILE_CATALOG_CODE,
    ).first()
    if definition is None:
        raise CatalogItemUnavailable("No technical file catalog is defined.")

    version = (
        ConfigurationVersion.objects.filter(
            definition=definition,
            status=ConfigurationStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )
    if version is None:
        raise CatalogItemUnavailable("No technical file catalog is published.")
    return version


def read_catalog_item(*, catalog_version: ConfigurationVersion, item_code: str) -> CatalogItemRules:
    """Read an item from one specific catalog version, current or not."""
    items: list[dict[str, Any]] = catalog_version.content_json.get("catalog_items", [])
    item = next((entry for entry in items if entry.get("item_code") == item_code), None)
    if item is None:
        raise CatalogItemUnavailable(f"Catalog item {item_code} is not listed.")
    if item.get("enabled", True) is False:
        raise CatalogItemUnavailable(f"Catalog item {item_code} is disabled.")

    return CatalogItemRules(
        item_code=item_code,
        name=item["name"],
        allowed_mime_types=frozenset(item["allowed_mime_types"]),
        max_bytes=min(int(item["max_bytes"]), hard_max_bytes()),
        preview_enabled=bool(item["preview_enabled"]),
        default_sensitivity_level=item["default_sensitivity_level"],
        retention_years=int(item["retention_years"]),
        catalog_version_public_id=catalog_version.public_id,
        catalog_content_digest=catalog_version.content_digest,
    )


def resolve_catalog_item(*, organization: Organization, item_code: str) -> CatalogItemRules:
    """Read an item from whichever catalog version is published right now."""
    return read_catalog_item(
        catalog_version=published_catalog(organization),
        item_code=item_code,
    )
