"""Product query permission projection."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.products.models import ProductAsset


@pytest.mark.django_db
def test_owner_search_includes_sensitive_formula_summary(
    api_client: APIClient,
    product_manager: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=product_manager)
    response = api_client.get("/api/v1/products", {"search": "yogurt"})
    assert response.status_code == 200
    items = response.json()["items"]
    item = next(row for row in items if row["public_id"] == str(active_product.public_id))
    assert item["formula_summary"] == "12g protein per serving"
