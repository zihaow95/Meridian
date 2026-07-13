"""Read queries and field projection for product assets."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.products.models import (
    SKU,
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ProductAsset,
    ProductVersion,
)


def _can_read_sensitive(user: User, product: ProductAsset) -> bool:
    return authorize(
        subject_for(user),
        action="product.read_sensitive",
        resource=ResourceDescriptor(
            resource_type="product",
            public_id=product.public_id,
            organization_id=product.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
        ),
        context=AuthorizationContext.current(),
    ).allowed


def _formula_summary(product: ProductAsset) -> str | None:
    value = (
        AttributeGroupValue.objects.filter(
            organization_id=product.organization_id,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=product.id,
            value_status=AttributeValueStatus.EFFECTIVE,
            group_definition__group_code="PRODUCT_DEFINITION",
        )
        .order_by("-updated_at")
        .first()
    )
    if value is None:
        return None
    summary = value.values_json.get("formula_summary")
    return str(summary) if summary is not None else None


def search_products(*, user: User, search: str = "") -> list[dict[str, Any]]:
    queryset = ProductAsset.objects.filter(organization_id=user.organization_id)
    if search:
        queryset = queryset.filter(name__icontains=search)
    queryset = queryset.order_by("name", "business_no")
    items: list[dict[str, Any]] = []
    for product in queryset:
        items.append(serialize_product_summary(product, user=user))
    return items


def serialize_product_summary(product: ProductAsset, *, user: User) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "public_id": str(product.public_id),
        "business_no": product.business_no,
        "name": product.name,
        "lifecycle_status": product.lifecycle_status,
    }
    if _can_read_sensitive(user, product):
        formula_summary = _formula_summary(product)
        if formula_summary is not None:
            payload["formula_summary"] = formula_summary
    return payload


def get_product_detail(*, user: User, public_id: UUID) -> dict[str, Any] | None:
    product = (
        ProductAsset.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        )
        .select_related("primary_version")
        .first()
    )
    if product is None:
        return None
    return serialize_product_detail(product, user=user)


def serialize_product_detail(product: ProductAsset, *, user: User) -> dict[str, Any]:
    can_sensitive = _can_read_sensitive(user, product)
    payload: dict[str, Any] = {
        "public_id": str(product.public_id),
        "business_no": product.business_no,
        "name": product.name,
        "lifecycle_status": product.lifecycle_status,
        "brand_code": product.brand_code,
        "category_code": product.category_code,
        "versions": [
            serialize_product_version(version)
            for version in ProductVersion.objects.filter(product=product).order_by("version_code")
        ],
        "external_bindings": list_product_external_bindings(product),
    }
    if can_sensitive:
        formula_summary = _formula_summary(product)
        if formula_summary is not None:
            payload["formula_summary"] = formula_summary
    return payload


def list_product_external_bindings(product: ProductAsset) -> list[dict[str, Any]]:
    from apps.integrations.models import BindingStatus, ExternalBinding

    rows = ExternalBinding.objects.filter(
        organization_id=product.organization_id,
        internal_object_type="product",
        internal_object_id=product.id,
        binding_status=BindingStatus.ACTIVE,
    ).order_by("source_system", "object_type", "external_id")
    return [
        {
            "public_id": str(row.public_id),
            "source_system": row.source_system,
            "object_type": row.object_type,
            "external_id": row.external_id,
            "binding_status": row.binding_status,
        }
        for row in rows
    ]


def serialize_product_version(version: ProductVersion) -> dict[str, Any]:
    return {
        "public_id": str(version.public_id),
        "version_code": version.version_code,
        "version_name": version.version_name,
        "status": version.status,
        "skus": [serialize_sku(sku) for sku in SKU.objects.filter(product_version=version)],
    }


def serialize_sku(sku: SKU) -> dict[str, Any]:
    return {
        "public_id": str(sku.public_id),
        "sku_code": sku.sku_code,
        "name": sku.name,
        "specification": sku.specification,
    }
