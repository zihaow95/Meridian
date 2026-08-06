"""Entering one historical product through the form.

The API's job here is to surface duplicate candidates and then do exactly what
the user decided. It never merges products, and it never quietly creates a
second one when a submission is replayed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.products.models import SKU, ProductAsset, ProductChangeSet

pytestmark = pytest.mark.django_db

PAYLOAD: dict[str, Any] = {
    "name": "老酸奶 200g",
    "category_code": "YOGURT",
    "brand_code": "BRAND-A",
    "business_no": "LEG-API-0001",
    "sku_code": "SKU-API-0001",
    "barcode": "6900000000011",
    "specification": "200g/杯",
}


@pytest.fixture
def entry_user(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "legacy_baseline.draft.create", "product_change_set")
    return active_user


@pytest.fixture
def client(entry_user: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(entry_user)
    return api


def create(client: APIClient, **body: Any) -> Any:
    return client.post(
        reverse("legacy-baseline-create"),
        {
            "payload": {**PAYLOAD, **body.pop("payload", {})},
            "idempotency_key": body.pop("idempotency_key", "form-api-1"),
            **body,
        },
        format="json",
    )


def test_the_form_creates_a_product_and_a_baseline_draft(client: APIClient) -> None:
    response = create(client)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["duplicate_candidates"] == []
    change_set = ProductChangeSet.objects.get(public_id=body["change_set_public_id"])
    assert str(change_set.product.public_id) == body["product_public_id"]


def test_replaying_the_same_submission_returns_the_first_draft(client: APIClient) -> None:
    first = create(client).json()

    second = create(client)

    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["change_set_public_id"] == first["change_set_public_id"]
    assert ProductAsset.objects.count() == 1


def test_a_matching_business_number_stops_the_form_until_the_user_decides(
    client: APIClient, product_asset: ProductAsset
) -> None:
    response = create(client, payload={"business_no": product_asset.business_no})

    assert response.status_code == 400
    body = response.json()
    assert body["details"]["reason"] == "DUPLICATE_REQUIRES_DECISION"
    assert body["details"]["duplicate_candidates"][0]["blocking"] is True
    assert ProductChangeSet.objects.count() == 0


def test_an_explicit_create_decision_proceeds_despite_a_shared_barcode(
    client: APIClient, active_product: ProductAsset
) -> None:
    """Two products may genuinely carry the same barcode during a migration."""

    sku = SKU.objects.get(product_version__product=active_product)
    sku.barcode = PAYLOAD["barcode"]
    sku.save(update_fields=["barcode"])

    response = create(client, decision="CREATE")

    assert response.status_code == 201
    assert response.json()["duplicate_candidates"][0]["match_type"] == "BARCODE_EXACT"
    assert ProductAsset.objects.filter(business_no=PAYLOAD["business_no"]).exists()


def test_creating_anyway_still_refuses_a_business_number_that_is_taken(
    client: APIClient, product_asset: ProductAsset
) -> None:
    response = create(client, payload={"business_no": product_asset.business_no}, decision="CREATE")

    assert response.status_code == 400
    assert response.json()["details"]["reason"] == "BUSINESS_NO_TAKEN"
    assert ProductChangeSet.objects.count() == 0


def test_a_link_decision_reuses_the_existing_product(
    client: APIClient, product_asset: ProductAsset
) -> None:
    response = create(
        client,
        payload={"business_no": product_asset.business_no},
        decision="LINK",
        target_product_public_id=str(product_asset.public_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["product_public_id"] == str(product_asset.public_id)
    assert ProductAsset.objects.count() == 1
    change_set = ProductChangeSet.objects.get(public_id=body["change_set_public_id"])
    assert change_set.change_scope["linked_existing_product"] is True


def test_a_link_decision_without_a_target_is_refused(
    client: APIClient, product_asset: ProductAsset
) -> None:
    response = create(client, payload={"business_no": product_asset.business_no}, decision="LINK")

    assert response.status_code == 400
    assert ProductChangeSet.objects.count() == 0


def test_a_missing_name_is_refused_before_anything_is_written(client: APIClient) -> None:
    response = create(client, payload={"name": ""})

    assert response.status_code == 400
    assert ProductAsset.objects.count() == 0


def test_the_form_is_closed_to_users_without_the_action(
    another_active_user: User,
) -> None:
    api = APIClient()
    api.force_authenticate(another_active_user)

    response = api.post(
        reverse("legacy-baseline-create"),
        {"payload": PAYLOAD, "idempotency_key": "nope"},
        format="json",
    )

    assert response.status_code == 404
    assert ProductAsset.objects.count() == 0
