"""Product dossier API contract and permission projection."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.products.models import ProductAsset, ProductLifecycleStatus, ProductSourceType


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
