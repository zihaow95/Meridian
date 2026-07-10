"""Factories for product attribute schema test fixtures."""

from __future__ import annotations

from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.products.models import (
    AttributeDefinition,
    AttributeFieldType,
    AttributeGroupDefinition,
    AttributeOwnerLevel,
    AttributeSchemaStatus,
    AttributeSchemaVersion,
)


def build_published_product_schema(
    *,
    organization: Organization,
    category_code: str = "YOGURT",
) -> AttributeSchemaVersion:
    schema_version = AttributeSchemaVersion.objects.create(
        organization=organization,
        schema_code="PRODUCT_PROFILE",
        version_number=1,
        category_code=category_code,
        status=AttributeSchemaStatus.PUBLISHED,
        published_at=timezone.now(),
    )
    product_definition = AttributeGroupDefinition.objects.create(
        organization=organization,
        schema_version=schema_version,
        group_code="PRODUCT_DEFINITION",
        name="Product definition",
        owner_level=AttributeOwnerLevel.PRODUCT,
        display_order=1,
    )
    AttributeDefinition.objects.create(
        organization=organization,
        group_definition=product_definition,
        field_code="core_selling_points",
        field_name="Core selling points",
        field_type=AttributeFieldType.TEXT,
        display_order=1,
    )
    quality_compliance = AttributeGroupDefinition.objects.create(
        organization=organization,
        schema_version=schema_version,
        group_code="QUALITY_COMPLIANCE",
        name="Quality and compliance",
        owner_level=AttributeOwnerLevel.VERSION,
        display_order=2,
    )
    AttributeDefinition.objects.create(
        organization=organization,
        group_definition=quality_compliance,
        field_code="storage_condition",
        field_name="Storage condition label",
        field_type=AttributeFieldType.TEXT,
        display_order=1,
    )
    return schema_version
