"""Read queries and field projection for product assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import DataSensitivityLevel, RoleStatus
from apps.authorization.models.special_grant import SpecialGrant, SpecialGrantStatus
from apps.authorization.models.troubleshoot import TroubleshootAccess, TroubleshootAccessStatus
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

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100
_READ_BASIC_ACTION = "product.read_basic"


@dataclass(frozen=True)
class ProductSearchPage:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    count: int


def _can_read_basic(user: User, product: ProductAsset) -> bool:
    return authorize(
        subject_for(user),
        action=_READ_BASIC_ACTION,
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


def _has_org_level_product_read(user: User) -> bool:
    """Whether RBAC grants organization-wide product.read_basic.

    Mirrors authorize() for INTERNAL sensitivity: platform roles are not blocked
    for product.read_basic unless the resource is highly sensitive.
    """
    context = AuthorizationContext.current()
    return (
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=context.as_of,
            scope_type=ScopeType.ORGANIZATION,
            role__status=RoleStatus.ACTIVE,
            role__permissions__action__action_code=_READ_BASIC_ACTION,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=context.as_of))
        .exists()
    )


def _extra_granted_product_public_ids(user: User) -> tuple[bool, set[UUID]]:
    """Return (covers_all_org_products, specific_public_ids) from grants/access."""
    context = AuthorizationContext.current()
    covers_all = False
    public_ids: set[UUID] = set()

    grants = SpecialGrant.objects.filter(
        grantee=user,
        status=SpecialGrantStatus.ACTIVE,
        resource_type="product",
        valid_from__lte=context.as_of,
        valid_to__gt=context.as_of,
    )
    for grant in grants:
        if _READ_BASIC_ACTION not in grant.actions:
            continue
        if grant.resource_public_id is None:
            covers_all = True
        else:
            public_ids.add(grant.resource_public_id)

    accesses = TroubleshootAccess.objects.filter(
        user=user,
        status=TroubleshootAccessStatus.ACTIVE,
        resource_type="product",
        valid_from__lte=context.as_of,
        valid_to__gt=context.as_of,
    )
    for access in accesses:
        if _READ_BASIC_ACTION not in access.actions:
            continue
        if access.resource_public_id is None:
            covers_all = True
        else:
            public_ids.add(access.resource_public_id)

    return covers_all, public_ids


def _candidate_products_for_user(user: User) -> QuerySet[ProductAsset]:
    """Candidates covering all authorize() allow paths for product.read_basic."""
    from apps.projects.models import ProjectMember, ProjectRole

    base = ProductAsset.objects.filter(organization_id=user.organization_id)
    if _has_org_level_product_read(user):
        return base

    grant_covers_all, granted_public_ids = _extra_granted_product_public_ids(user)
    if grant_covers_all:
        return base

    membership_project_ids = ProjectMember.objects.filter(
        user=user,
        project_role=ProjectRole.MEMBER,
        active_to__isnull=True,
        project__organization_id=user.organization_id,
    ).values_list("project_id", flat=True)

    conditions = (
        Q(product_owner_id=user.id)
        | Q(source_project__leader_id=user.id)
        | Q(source_project_id__in=membership_project_ids)
    )
    if granted_public_ids:
        conditions |= Q(public_id__in=granted_public_ids)
    return base.filter(conditions).distinct()


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
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> ProductSearchPage:
    page = max(page, 1)
    page_size = min(max(page_size, 1), _MAX_PAGE_SIZE)

    queryset = _candidate_products_for_user(user)
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
    queryset = queryset.order_by("name", "business_no", "public_id")

    allowed_ids: list[int] = []
    for product in queryset.only("id", "public_id", "organization_id").iterator(chunk_size=200):
        if _can_read_basic(user, product):
            allowed_ids.append(product.id)

    count = len(allowed_ids)
    start = (page - 1) * page_size
    end = start + page_size
    page_ids = allowed_ids[start:end]
    if not page_ids:
        return ProductSearchPage(items=[], page=page, page_size=page_size, count=count)

    products_by_id = {
        product.id: product
        for product in ProductAsset.objects.filter(id__in=page_ids).select_related("product_owner")
    }
    items = [
        serialize_product_summary(products_by_id[product_id], user=user)
        for product_id in page_ids
        if product_id in products_by_id
    ]
    return ProductSearchPage(
        items=items,
        page=page,
        page_size=page_size,
        count=count,
    )


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
