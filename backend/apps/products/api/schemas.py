"""OpenAPI schemas for product APIs."""

from __future__ import annotations

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


def _nested(schema: serializers.Serializer, *, allow_null: bool = False) -> serializers.Serializer:
    """Reuse a schema inside another one.

    DRF binds a field to the serializer that declares it, so the same instance
    cannot appear in two places. Options must be passed to the constructor:
    ``Field.__deepcopy__`` rebuilds from the original arguments and drops
    anything assigned afterwards.
    """
    return type(schema)(allow_null=allow_null)


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
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "count": serializers.IntegerField(),
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
        "assigned_confirmer_public_id": serializers.UUIDField(required=False, allow_null=True),
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
        "can_reassign_confirmer": serializers.BooleanField(),
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

REASSIGN_CONFIRMER_REQUEST_SCHEMA = inline_serializer(
    name="ReassignConfirmerRequest",
    fields={
        "group_value_public_id": serializers.UUIDField(),
        "confirmer_public_id": serializers.UUIDField(),
        "reason": serializers.CharField(required=False),
    },
)

CONFIRMER_CANDIDATE_SCHEMA = inline_serializer(
    name="ConfirmerCandidate",
    fields={
        "public_id": serializers.UUIDField(),
        "display_name": serializers.CharField(),
    },
)

CONFIRMER_CANDIDATE_PAGE_SCHEMA = inline_serializer(
    name="ConfirmerCandidatePage",
    fields={
        "items": serializers.ListField(child=CONFIRMER_CANDIDATE_SCHEMA),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "count": serializers.IntegerField(),
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

LEGACY_MATERIAL_SCHEMA = inline_serializer(
    name="LegacyMaterialSubmission",
    fields={
        "public_id": serializers.UUIDField(),
        "document_version_public_id": serializers.UUIDField(),
        "processing_status": serializers.CharField(),
        "source_note": serializers.CharField(allow_blank=True),
        "original_file_date": serializers.DateField(allow_null=True),
        "claimed_version": serializers.CharField(allow_blank=True),
        "claimed_effective_from": serializers.DateField(allow_null=True),
        "sha256": serializers.CharField(),
        "submitted_by_public_id": serializers.UUIDField(),
        "verified_by_public_id": serializers.UUIDField(allow_null=True),
        "verification_note": serializers.CharField(allow_blank=True),
        "duplicate_candidates": serializers.ListField(required=False),
    },
)

LEGACY_MATERIAL_PAGE_SCHEMA = inline_serializer(
    name="LegacyMaterialSubmissionPage",
    fields={"items": serializers.ListField(child=_nested(LEGACY_MATERIAL_SCHEMA))},
)

LEGACY_MATERIAL_CREATE_REQUEST_SCHEMA = inline_serializer(
    name="LegacyMaterialSubmissionCreateRequest",
    fields={
        "document_version_public_id": serializers.UUIDField(),
        "idempotency_key": serializers.CharField(),
        "source_note": serializers.CharField(required=False, allow_blank=True),
        "original_file_date": serializers.DateField(required=False, allow_null=True),
        "claimed_version": serializers.CharField(required=False, allow_blank=True),
        "claimed_effective_from": serializers.DateField(required=False, allow_null=True),
    },
)

LEGACY_MATERIAL_VERIFY_REQUEST_SCHEMA = inline_serializer(
    name="LegacyMaterialSubmissionVerifyRequest",
    fields={
        "decision": serializers.CharField(),
        "note": serializers.CharField(required=False, allow_blank=True),
    },
)

MATERIAL_CONFIRMATION_SCHEMA = inline_serializer(
    name="MaterialConfirmation",
    fields={
        "public_id": serializers.UUIDField(),
        "decision": serializers.CharField(),
        "confirmer_public_id": serializers.UUIDField(allow_null=True),
        "content_hash": serializers.CharField(),
        "requested_at": serializers.DateTimeField(),
        "decided_at": serializers.DateTimeField(allow_null=True),
    },
)

PRODUCT_MATERIAL_SCHEMA = inline_serializer(
    name="ProductMaterial",
    fields={
        "public_id": serializers.UUIDField(),
        "material_type_code": serializers.CharField(),
        "version_no": serializers.IntegerField(),
        "material_status": serializers.CharField(),
        "is_current": serializers.BooleanField(),
        "document_version_public_id": serializers.UUIDField(),
        "original_filename": serializers.CharField(),
        "confirmation": _nested(MATERIAL_CONFIRMATION_SCHEMA, allow_null=True),
    },
)

MATERIAL_CHAIN_SCHEMA = inline_serializer(
    name="ProductMaterialChain",
    fields={"items": serializers.ListField(child=_nested(PRODUCT_MATERIAL_SCHEMA))},
)

MATERIAL_CHAIN_CREATE_REQUEST_SCHEMA = inline_serializer(
    name="ProductMaterialChainCreateRequest",
    fields={
        "material_type_code": serializers.CharField(),
        "ordered_submission_ids": serializers.ListField(child=serializers.UUIDField()),
        "current_submission_id": serializers.UUIDField(),
    },
)

MATERIAL_GROUP_PAGE_SCHEMA = inline_serializer(
    name="ProductMaterialGroupPage",
    fields={
        "items": serializers.ListField(
            child=inline_serializer(
                name="ProductMaterialGroup",
                fields={
                    "material_type_code": serializers.CharField(),
                    "current": _nested(PRODUCT_MATERIAL_SCHEMA, allow_null=True),
                    "history": serializers.ListField(child=_nested(PRODUCT_MATERIAL_SCHEMA)),
                },
            )
        )
    },
)

MATERIAL_COMPLETENESS_ITEM_SCHEMA = inline_serializer(
    name="ProductMaterialCompletenessItem",
    fields={
        "material_type_code": serializers.CharField(),
        "requirement": serializers.CharField(),
        "state": serializers.CharField(),
    },
)

MATERIAL_COMPLETENESS_SCHEMA = inline_serializer(
    name="ProductMaterialCompleteness",
    fields={
        "requirement_version_public_id": serializers.UUIDField(),
        "requirement_version_number": serializers.IntegerField(),
        "requirement_content_digest": serializers.CharField(allow_blank=True),
        "is_complete": serializers.BooleanField(),
        "blocking_material_type_codes": serializers.ListField(child=serializers.CharField()),
        "items": serializers.ListField(child=_nested(MATERIAL_COMPLETENESS_ITEM_SCHEMA)),
    },
)

MATERIAL_CONFIRMATION_REQUEST_SCHEMA = inline_serializer(
    name="MaterialConfirmationCreateRequest",
    fields={
        "confirmer_public_id": serializers.UUIDField(),
        "comment": serializers.CharField(required=False, allow_blank=True),
    },
)

LEGACY_BASELINE_CREATE_REQUEST_SCHEMA = inline_serializer(
    name="LegacyBaselineDraftCreateRequest",
    fields={
        "payload": serializers.DictField(),
        "idempotency_key": serializers.CharField(),
        "decision": serializers.CharField(required=False, allow_blank=True),
        "target_product_public_id": serializers.UUIDField(required=False, allow_null=True),
    },
)

LEGACY_BASELINE_DRAFT_SCHEMA = inline_serializer(
    name="LegacyBaselineDraft",
    fields={
        "change_set_public_id": serializers.UUIDField(),
        "product_public_id": serializers.UUIDField(),
        "created": serializers.BooleanField(),
        "duplicate_candidates": serializers.ListField(),
    },
)

MATERIAL_CONFIRMATION_DECIDE_REQUEST_SCHEMA = inline_serializer(
    name="MaterialConfirmationDecideRequest",
    fields={
        "decision": serializers.CharField(),
        "comment": serializers.CharField(required=False, allow_blank=True),
    },
)
