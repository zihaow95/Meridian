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
        "barcode": serializers.CharField(required=False),
        "channels": serializers.ListField(required=False),
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

EXTERNAL_BINDING_SCHEMA = inline_serializer(
    name="ExternalBinding",
    fields={
        "public_id": serializers.UUIDField(),
        "source_system": serializers.CharField(),
        "object_type": serializers.CharField(),
        "external_id": serializers.CharField(),
        "binding_status": serializers.CharField(),
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
        "external_bindings": serializers.ListField(child=EXTERNAL_BINDING_SCHEMA),
    },
)

CHANGE_SET_ATTRIBUTE_GROUP_SCHEMA = inline_serializer(
    name="ChangeSetAttributeGroup",
    fields={
        "public_id": serializers.UUIDField(),
        "group_code": serializers.CharField(),
        "group_name": serializers.CharField(),
        "requires_confirmation": serializers.BooleanField(),
        "content_hash": serializers.CharField(),
        "values_json": serializers.DictField(),
        "confirmation_status": serializers.CharField(),
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
        "change_scope": serializers.DictField(required=False),
        "attribute_groups": serializers.ListField(child=CHANGE_SET_ATTRIBUTE_GROUP_SCHEMA),
    },
)

CREATE_CHANGE_SET_REQUEST_SCHEMA = inline_serializer(
    name="CreateChangeSetRequest",
    fields={
        "change_type": serializers.CharField(),
        "title": serializers.CharField(required=False),
        "base_version_public_id": serializers.UUIDField(required=False),
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

UPDATE_SCOPE_REQUEST_SCHEMA = inline_serializer(
    name="UpdateChangeSetScopeRequest",
    fields={
        "version_no": serializers.IntegerField(),
        "skus": serializers.ListField(required=False),
        "channels": serializers.ListField(required=False),
        "scopes": serializers.ListField(required=False),
        "effective_from": serializers.DateTimeField(required=False),
    },
)

ATTRIBUTE_CONFIRMATION_REQUEST_SCHEMA = inline_serializer(
    name="AttributeConfirmationRequest",
    fields={
        "group_value_public_id": serializers.UUIDField(),
        "content_hash": serializers.CharField(),
        "comment": serializers.CharField(required=False),
    },
)

CHANGE_SET_DIFF_SCHEMA = inline_serializer(
    name="ProductChangeSetDiffResponse",
    fields={
        "change_set_public_id": serializers.UUIDField(),
        "changed_fields": serializers.ListField(),
    },
)

UPSERT_EXTERNAL_BINDING_REQUEST_SCHEMA = inline_serializer(
    name="UpsertExternalBindingRequest",
    fields={
        "source_system": serializers.CharField(),
        "object_type": serializers.CharField(),
        "external_id": serializers.CharField(),
    },
)

DECIDE_IMPORT_ITEM_REQUEST_SCHEMA = inline_serializer(
    name="DecideImportItemRequest",
    fields={
        "row_number": serializers.IntegerField(),
        "decision": serializers.CharField(),
        "target_product_public_id": serializers.UUIDField(required=False),
    },
)

DECIDE_IMPORT_ITEM_RESPONSE_SCHEMA = inline_serializer(
    name="DecideImportItemResponse",
    fields={
        "row_number": serializers.IntegerField(),
        "decision": serializers.CharField(),
        "target_product_public_id": serializers.UUIDField(required=False, allow_null=True),
    },
)
