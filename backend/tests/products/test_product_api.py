"""Product dossier API contract and permission projection."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.products.models import ProductAsset


@pytest.mark.django_db
def test_basic_search_hides_sensitive_fields(
    api_client: APIClient,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get("/api/v1/products", {"search": "yogurt"})
    assert response.status_code == 200
    items = response.json()["items"]
    item = next(row for row in items if row["public_id"] == str(active_product.public_id))
    assert "formula_summary" not in item


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
