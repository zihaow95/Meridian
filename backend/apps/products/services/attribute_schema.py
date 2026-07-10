"""Resolve and validate published product attribute schemas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from apps.configuration.models import compute_content_digest
from apps.identity.models.organization import Organization
from apps.products.errors import (
    AttributeGroupNotFound,
    AttributeSchemaNotPublished,
    AttributeValueInvalid,
)
from apps.products.models import (
    AttributeDefinition,
    AttributeFieldType,
    AttributeGroupDefinition,
    AttributeSchemaStatus,
    AttributeSchemaVersion,
)

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ResolvedAttributeSchema:
    schema_version: AttributeSchemaVersion
    group_definitions: tuple[AttributeGroupDefinition, ...]

    def group_by_code(self, group_code: str) -> AttributeGroupDefinition:
        for group in self.group_definitions:
            if group.group_code == group_code:
                return group
        raise AttributeGroupNotFound()


def resolve_product_attribute_schema(
    organization: Organization | int,
    *,
    category_code: str,
    as_of: datetime | None = None,
) -> ResolvedAttributeSchema:
    organization_id = organization.id if isinstance(organization, Organization) else organization
    queryset = AttributeSchemaVersion.objects.filter(
        organization_id=organization_id,
        category_code=category_code,
        status=AttributeSchemaStatus.PUBLISHED,
    )
    if as_of is not None:
        queryset = queryset.filter(published_at__lte=as_of)
    schema_version = queryset.order_by("-version_number", "-published_at").first()
    if schema_version is None:
        raise AttributeSchemaNotPublished()
    groups = tuple(
        AttributeGroupDefinition.objects.filter(schema_version=schema_version)
        .prefetch_related("field_definitions")
        .order_by("display_order", "group_code")
    )
    return ResolvedAttributeSchema(schema_version=schema_version, group_definitions=groups)


def compute_attribute_content_hash(values: dict[str, Any]) -> str:
    return compute_content_digest(values)


def validate_group_values(
    *,
    group_definition: AttributeGroupDefinition,
    values: dict[str, Any],
) -> dict[str, Any]:
    field_definitions = {
        definition.field_code: definition for definition in group_definition.field_definitions.all()
    }
    unknown_codes = set(values) - set(field_definitions)
    if unknown_codes:
        unknown = sorted(unknown_codes)[0]
        raise AttributeValueInvalid(
            field_code=unknown,
            reason="Unknown attribute field code.",
        )

    normalized: dict[str, Any] = {}
    for field_code, definition in field_definitions.items():
        if field_code not in values:
            if definition.required:
                raise AttributeValueInvalid(
                    field_code=field_code,
                    reason="Required attribute is missing.",
                )
            continue
        normalized[field_code] = _validate_field_value(definition, values[field_code])
    return normalized


def _validate_field_value(definition: AttributeDefinition, value: Any) -> Any:
    field_type = AttributeFieldType(definition.field_type)
    rules = definition.validation_rules or {}

    if field_type == AttributeFieldType.TEXT:
        if not isinstance(value, str):
            raise AttributeValueInvalid(field_code=definition.field_code, reason="Expected text.")
        return value

    if field_type == AttributeFieldType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise AttributeValueInvalid(field_code=definition.field_code, reason="Expected number.")
        return value

    if field_type == AttributeFieldType.MONEY:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise AttributeValueInvalid(
                field_code=definition.field_code,
                reason="Expected monetary amount.",
            ) from exc
        return format(amount, "f")

    if field_type == AttributeFieldType.DATE:
        if not isinstance(value, str) or not _DATE_PATTERN.match(value):
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Expected ISO date."
            )
        return value

    if field_type == AttributeFieldType.SINGLE_SELECT:
        if not isinstance(value, str):
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Expected option code."
            )
        options = rules.get("options", [])
        if options and value not in options:
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Invalid option code."
            )
        return value

    if field_type == AttributeFieldType.MULTI_SELECT:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Expected option list."
            )
        options = rules.get("options", [])
        if options and any(item not in options for item in value):
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Invalid option code."
            )
        return value

    if field_type == AttributeFieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise AttributeValueInvalid(
                field_code=definition.field_code, reason="Expected boolean."
            )
        return value

    if field_type in {
        AttributeFieldType.USER_REF,
        AttributeFieldType.DEPARTMENT_REF,
        AttributeFieldType.OBJECT_REF,
        AttributeFieldType.FILE_REF,
        AttributeFieldType.IMAGE_REF,
    }:
        if not isinstance(value, str) or not _UUID_PATTERN.match(value):
            try:
                normalized = str(UUID(str(value)))
            except (TypeError, ValueError) as exc:
                raise AttributeValueInvalid(
                    field_code=definition.field_code,
                    reason="Expected UUID reference.",
                ) from exc
            return normalized
        return value

    if field_type == AttributeFieldType.DETAIL_TABLE:
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise AttributeValueInvalid(
                field_code=definition.field_code,
                reason="Expected structured detail rows.",
            )
        return value

    raise AttributeValueInvalid(field_code=definition.field_code, reason="Unsupported field type.")
