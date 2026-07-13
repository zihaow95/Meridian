"""Read queries and field projection for product assets."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

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


def _can_read_basic(user: User, product: ProductAsset) -> bool:
    return authorize(
        subject_for(user),
        action="product.read_basic",
        resource=ResourceDescriptor(
            resource_type="product",
            public_id=product.public_id,
            organization_id=product.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


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


def _apply_product_filters(
    queryset: QuerySet[ProductAsset],
    *,
    search: str = "",
    brand_code: str = "",
    category_code: str = "",
    lifecycle_status: str = "",
    owner_public_id: str = "",
    sku_code: str = "",
    external_id: str = "",
    channel_code: str = "",
) -> QuerySet[ProductAsset]:
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(business_no__icontains=search))
    if brand_code:
        queryset = queryset.filter(brand_code__iexact=brand_code)
    if category_code:
        queryset = queryset.filter(category_code__iexact=category_code)
    if lifecycle_status:
        queryset = queryset.filter(lifecycle_status=lifecycle_status)
    if owner_public_id:
        queryset = queryset.filter(product_owner__public_id=owner_public_id)
    if sku_code:
        queryset = queryset.filter(versions__skus__sku_code__icontains=sku_code)
    if external_id:
        from apps.integrations.models import BindingStatus, ExternalBinding

        bound_ids = ExternalBinding.objects.filter(
            internal_object_type="product",
            binding_status=BindingStatus.ACTIVE,
            external_id__icontains=external_id,
        ).values_list("internal_object_id", flat=True)
        queryset = queryset.filter(id__in=bound_ids)
    if channel_code:
        queryset = queryset.filter(
            versions__skus__channel_configurations__channel_code__iexact=channel_code
        )
    return queryset.distinct()


def search_products(
    *,
    user: User,
    search: str = "",
    brand_code: str = "",
    category_code: str = "",
    lifecycle_status: str = "",
    owner_public_id: str = "",
    sku_code: str = "",
    external_id: str = "",
    channel_code: str = "",
) -> list[dict[str, Any]]:
    queryset = ProductAsset.objects.filter(organization_id=user.organization_id)
    queryset = _apply_product_filters(
        queryset,
        search=search,
        brand_code=brand_code,
        category_code=category_code,
        lifecycle_status=lifecycle_status,
        owner_public_id=owner_public_id,
        sku_code=sku_code,
        external_id=external_id,
        channel_code=channel_code,
    )
    queryset = queryset.order_by("name", "business_no")
    items: list[dict[str, Any]] = []
    for product in queryset:
        if not _can_read_basic(user, product):
            continue
        items.append(serialize_product_summary(product, user=user))
    return items


def serialize_product_summary(product: ProductAsset, *, user: User) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "public_id": str(product.public_id),
        "business_no": product.business_no,
        "name": product.name,
        "lifecycle_status": product.lifecycle_status,
        "brand_code": product.brand_code,
        "category_code": product.category_code,
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
        .select_related("primary_version", "product_owner")
        .first()
    )
    if product is None:
        return None
    if not _can_read_basic(user, product):
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
    if product.product_owner_id is not None:
        payload["product_owner_public_id"] = str(product.product_owner.public_id)
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
        "skus": [
            serialize_sku(sku)
            for sku in SKU.objects.filter(product_version=version).prefetch_related(
                "channel_configurations"
            )
        ],
    }


def serialize_sku(sku: SKU) -> dict[str, Any]:
    return {
        "public_id": str(sku.public_id),
        "sku_code": sku.sku_code,
        "name": sku.name,
        "specification": sku.specification,
        "barcode": sku.barcode,
        "channels": [
            {
                "channel_code": config.channel_code,
                "channel_status": config.channel_status,
            }
            for config in sku.channel_configurations.all()
        ],
    }
