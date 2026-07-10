"""Stable domain error codes for product profile workflows."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class AttributeSchemaNotPublished(ApiError):
    code = "ATTRIBUTE_SCHEMA_NOT_PUBLISHED"
    message = "No published attribute schema is available for this product category."
    status_code = 409


class AttributeValueInvalid(ApiError):
    code = "ATTRIBUTE_VALUE_INVALID"
    message = "One or more attribute values failed schema validation."
    status_code = 400

    def __init__(self, *, field_code: str | None = None, reason: str | None = None) -> None:
        details: dict[str, str] = {}
        if field_code is not None:
            details["field_code"] = field_code
        if reason is not None:
            details["reason"] = reason
        super().__init__(details=details)


class ChangeSetVersionConflict(ApiError):
    code = "CHANGE_SET_VERSION_CONFLICT"
    message = "The product change set was updated by another operation."
    status_code = 409


class ChangeSetNotEditable(ApiError):
    code = "CHANGE_SET_NOT_EDITABLE"
    message = "The product change set cannot be edited in its current status."
    status_code = 409


class AttributeGroupNotFound(ApiError):
    code = "ATTRIBUTE_GROUP_NOT_FOUND"
    message = "The requested attribute group is not defined in the published schema."
    status_code = 400


class AttributeConfirmationInvalid(ApiError):
    code = "ATTRIBUTE_CONFIRMATION_INVALID"
    message = "The attribute confirmation request is invalid."
    status_code = 409

    def __init__(self, *, reason: str | None = None) -> None:
        details = {"reason": reason} if reason else {}
        super().__init__(details=details)


class ProductPublicationFailed(ApiError):
    code = "PRODUCT_PUBLICATION_FAILED"
    message = "Product publication failed."
    status_code = 500


class ChangeSetAlreadyPublished(ApiError):
    code = "CHANGE_SET_ALREADY_PUBLISHED"
    message = "The product change set has already been published."
    status_code = 409


class ProductBaselineChanged(ApiError):
    code = "PRODUCT_BASELINE_CHANGED"
    message = "The product baseline fingerprint has changed since the change set was created."
    status_code = 409
