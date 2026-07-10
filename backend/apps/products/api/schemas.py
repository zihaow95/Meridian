"""OpenAPI schemas for product APIs."""

from __future__ import annotations

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

PRODUCT_SUMMARY_SCHEMA = inline_serializer(
    name="ProductSummary",
    fields={
        "public_id": serializers.UUIDField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "lifecycle_status": serializers.CharField(),
        "formula_summary": serializers.CharField(required=False),
    },
)

PRODUCT_SEARCH_PAGE_SCHEMA = inline_serializer(
    name="ProductSearchPage",
    fields={
        "items": serializers.ListField(child=PRODUCT_SUMMARY_SCHEMA),
    },
)

PRODUCT_SKU_SCHEMA = inline_serializer(
    name="ProductSkuSummary",
    fields={
        "public_id": serializers.UUIDField(),
        "sku_code": serializers.CharField(),
        "name": serializers.CharField(),
        "specification": serializers.CharField(),
    },
)

PRODUCT_VERSION_SCHEMA = inline_serializer(
    name="ProductVersionSummary",
    fields={
        "public_id": serializers.UUIDField(),
        "version_code": serializers.CharField(),
        "version_name": serializers.CharField(),
        "status": serializers.CharField(),
        "skus": serializers.ListField(child=PRODUCT_SKU_SCHEMA),
    },
)

PRODUCT_DETAIL_SCHEMA = inline_serializer(
    name="ProductDetail",
    fields={
        "public_id": serializers.UUIDField(),
        "business_no": serializers.CharField(),
        "name": serializers.CharField(),
        "lifecycle_status": serializers.CharField(),
        "brand_code": serializers.CharField(),
        "category_code": serializers.CharField(),
        "formula_summary": serializers.CharField(required=False),
        "versions": serializers.ListField(child=PRODUCT_VERSION_SCHEMA),
    },
)

CHANGE_SET_DETAIL_SCHEMA = inline_serializer(
    name="ProductChangeSetDetail",
    fields={
        "public_id": serializers.UUIDField(),
        "change_type": serializers.CharField(),
        "status": serializers.CharField(),
        "title": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "product_public_id": serializers.UUIDField(),
    },
)

PUBLICATION_BLOCK_SCHEMA = inline_serializer(
    name="PublicationBlock",
    fields={
        "code": serializers.CharField(),
        "message": serializers.CharField(),
    },
)

PUBLICATION_VALIDATION_SCHEMA = inline_serializer(
    name="PublicationValidation",
    fields={
        "can_publish": serializers.BooleanField(),
        "blocks": serializers.ListField(child=PUBLICATION_BLOCK_SCHEMA),
    },
)

PUBLISH_CHANGE_SET_REQUEST_SCHEMA = inline_serializer(
    name="PublishChangeSetRequest",
    fields={
        "idempotency_key": serializers.CharField(),
    },
)

PUBLISH_CHANGE_SET_RESPONSE_SCHEMA = inline_serializer(
    name="PublishChangeSetResponse",
    fields={
        "change_set_public_id": serializers.UUIDField(),
        "product_version_public_id": serializers.UUIDField(),
        "product_lifecycle_status": serializers.CharField(),
    },
)

EDIT_CHANGE_SET_REQUEST_SCHEMA = inline_serializer(
    name="EditChangeSetRequest",
    fields={
        "version_no": serializers.IntegerField(),
        "group_code": serializers.CharField(),
        "values": serializers.DictField(),
    },
)
