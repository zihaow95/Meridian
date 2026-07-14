"""Product dossier API contract and permission projection."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.models.special_grant import SpecialGrant, SpecialGrantStatus
from apps.authorization.models.troubleshoot import TroubleshootAccess, TroubleshootAccessStatus
from apps.identity.models.user import User
from apps.products.models import (
    AttributeGroupDefinition,
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
)
from apps.products.services.attribute_schema import compute_attribute_content_hash


@pytest.mark.django_db
def test_unrelated_user_search_hides_products_without_read_basic(
    api_client: APIClient,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get("/api/v1/products", {"search": "yogurt"})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["count"] == 0
    items = body["items"]
    assert all(row["public_id"] != str(active_product.public_id) for row in items)


@pytest.mark.django_db
def test_unrelated_user_detail_is_not_found(
    api_client: APIClient,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get(f"/api/v1/products/{active_product.public_id}")
    assert response.status_code == 404


@pytest.mark.django_db
def test_product_detail_returns_public_identifiers(
    api_client: APIClient,
    product_manager: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=product_manager)
    response = api_client.get(f"/api/v1/products/{active_product.public_id}")
    assert response.status_code == 200
    body = response.json()
    assert "id" not in body
    assert body["public_id"] == str(active_product.public_id)
    assert body["versions"][0]["skus"][0]["public_id"]


@pytest.mark.django_db
def test_product_search_supports_brand_and_category_filters(
    api_client: APIClient,
    product_manager: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=product_manager)
    response = api_client.get(
        "/api/v1/products",
        {
            "brand_code": active_product.brand_code,
            "category_code": active_product.category_code,
        },
    )
    assert response.status_code == 200
    body = response.json()
    public_ids = {row["public_id"] for row in body["items"]}
    assert str(active_product.public_id) in public_ids
    assert body["count"] >= 1


@pytest.mark.django_db
def test_product_list_paginates_with_stable_sort_and_out_of_range_page(
    api_client: APIClient,
    organization,
    product_manager: User,
    published_product_schema,
) -> None:
    del published_product_schema
    for index in range(5):
        ProductAsset.objects.create(
            organization=organization,
            business_no=f"PRD-PAGE-{index:02d}",
            name=f"Paginated yogurt {index:02d}",
            category_code="YOGURT",
            brand_code="BRAND-A",
            source_type=ProductSourceType.NEW_PROJECT,
            lifecycle_status=ProductLifecycleStatus.ACTIVE,
            product_owner=product_manager,
        )
    api_client.force_authenticate(user=product_manager)

    first = api_client.get("/api/v1/products", {"search": "Paginated yogurt", "page_size": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["page"] == 1
    assert first_body["page_size"] == 2
    assert first_body["count"] == 5
    assert len(first_body["items"]) == 2
    assert [row["business_no"] for row in first_body["items"]] == [
        "PRD-PAGE-00",
        "PRD-PAGE-01",
    ]

    second = api_client.get(
        "/api/v1/products",
        {"search": "Paginated yogurt", "page": 2, "page_size": 2},
    )
    assert [row["business_no"] for row in second.json()["items"]] == [
        "PRD-PAGE-02",
        "PRD-PAGE-03",
    ]

    beyond = api_client.get(
        "/api/v1/products",
        {"search": "Paginated yogurt", "page": 99, "page_size": 2},
    )
    beyond_body = beyond.json()
    assert beyond_body["items"] == []
    assert beyond_body["count"] == 5
    assert beyond_body["page"] == 99


@pytest.mark.django_db
def test_product_list_candidate_filter_skips_unowned_org_products(
    api_client: APIClient,
    organization,
    product_manager: User,
    ordinary_employee: User,
    published_product_schema,
) -> None:
    del published_product_schema
    ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-OTHER",
        name="Other owner yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=ordinary_employee,
    )
    owned = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-OWNED",
        name="Owned yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=product_manager,
    )
    api_client.force_authenticate(user=product_manager)
    response = api_client.get("/api/v1/products", {"search": "yogurt", "page_size": 50})
    public_ids = {row["public_id"] for row in response.json()["items"]}
    assert str(owned.public_id) in public_ids
    assert all(row["business_no"] != "PRD-OTHER" for row in response.json()["items"])


@pytest.mark.django_db
def test_org_rbac_can_list_products_owned_by_others(
    api_client: APIClient,
    organization,
    product_manager: User,
    ordinary_employee: User,
    grant_action: Callable[..., None],
    published_product_schema,
) -> None:
    del published_product_schema
    grant_action(
        ordinary_employee,
        "product.read_basic",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    other = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RBAC",
        name="RBAC visible yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=product_manager,
    )
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get("/api/v1/products", {"search": "RBAC visible"})
    public_ids = {row["public_id"] for row in response.json()["items"]}
    assert str(other.public_id) in public_ids


@pytest.mark.django_db
def test_special_grant_can_list_granted_product(
    api_client: APIClient,
    organization,
    product_manager: User,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    now = timezone.now()
    SpecialGrant.objects.create(
        grantee=ordinary_employee,
        grantor=product_manager,
        resource_type="product",
        resource_public_id=active_product.public_id,
        actions=["product.read_basic"],
        max_sensitivity_level=DataSensitivityLevel.INTERNAL,
        valid_from=now - timedelta(hours=1),
        valid_to=now + timedelta(days=1),
        status=SpecialGrantStatus.ACTIVE,
        purpose="list grant",
    )
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get("/api/v1/products", {"search": active_product.name})
    public_ids = {row["public_id"] for row in response.json()["items"]}
    assert str(active_product.public_id) in public_ids


@pytest.mark.django_db
def test_troubleshoot_access_can_list_granted_product(
    api_client: APIClient,
    organization,
    product_manager: User,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    del organization
    now = timezone.now()
    TroubleshootAccess.objects.create(
        user=ordinary_employee,
        opened_by=product_manager,
        resource_type="product",
        resource_public_id=active_product.public_id,
        actions=["product.read_basic"],
        max_sensitivity_level=DataSensitivityLevel.INTERNAL,
        valid_from=now - timedelta(hours=1),
        valid_to=now + timedelta(days=1),
        status=TroubleshootAccessStatus.ACTIVE,
        purpose="list troubleshoot",
    )
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get("/api/v1/products", {"search": active_product.name})
    public_ids = {row["public_id"] for row in response.json()["items"]}
    assert str(active_product.public_id) in public_ids


@pytest.mark.django_db
def test_product_list_serializes_only_current_page_sensitive_fields(
    api_client: APIClient,
    organization,
    product_manager: User,
    grant_action: Callable[..., None],
    published_product_schema,
) -> None:
    del published_product_schema
    grant_action(
        product_manager,
        "product.read_basic",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    grant_action(
        product_manager,
        "product.read_sensitive",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    group = AttributeGroupDefinition.objects.get(
        schema_version__organization=organization,
        group_code="PRODUCT_DEFINITION",
    )
    for index in range(8):
        product = ProductAsset.objects.create(
            organization=organization,
            business_no=f"PRD-Q-{index:02d}",
            name=f"Query yogurt {index:02d}",
            category_code="YOGURT",
            source_type=ProductSourceType.NEW_PROJECT,
            lifecycle_status=ProductLifecycleStatus.ACTIVE,
            product_owner=product_manager,
        )
        values = {"formula_summary": f"formula-{index}"}
        AttributeGroupValue.objects.create(
            organization=organization,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=product.id,
            group_definition=group,
            schema_version=group.schema_version,
            values_json=values,
            content_hash=compute_attribute_content_hash(values),
            value_status=AttributeValueStatus.EFFECTIVE,
        )

    api_client.force_authenticate(user=product_manager)
    with CaptureQueriesContext(connection) as captured:
        response = api_client.get(
            "/api/v1/products",
            {"search": "Query yogurt", "page_size": 2},
        )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    formula_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "products_attribute_group_value" in query["sql"].lower()
    ]
    assert len(formula_queries) <= 4
