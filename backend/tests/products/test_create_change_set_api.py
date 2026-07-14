"""Create change-set API for iterations on existing products."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity.models.user import User
from apps.products.models import ChangeSetType, ProductAsset, ProductChangeSet


@pytest.mark.django_db
def test_owner_can_create_iteration_on_active_product(
    api_client: APIClient,
    product_manager: User,
    active_product: ProductAsset,
) -> None:
    assert active_product.primary_version_id is not None
    api_client.force_authenticate(user=product_manager)
    response = api_client.post(
        f"/api/v1/products/{active_product.public_id}/change-sets",
        {"change_type": ChangeSetType.ITERATION, "title": "Quality iteration"},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["change_type"] == ChangeSetType.ITERATION
    assert body["title"] == "Quality iteration"
    assert body["product_public_id"] == str(active_product.public_id)
    assert body["status"] == "DRAFT"
    assert "attribute_groups" in body
    assert body["attribute_groups"] == []

    change_set = ProductChangeSet.objects.get(public_id=body["public_id"])
    assert change_set.base_version_id == active_product.primary_version_id
    assert change_set.base_fingerprint
    assert change_set.project_candidate_id is None
    assert change_set.created_by_id == product_manager.id


@pytest.mark.django_db
def test_unrelated_user_denied_creating_change_set(
    api_client: APIClient,
    ordinary_employee: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.post(
        f"/api/v1/products/{active_product.public_id}/change-sets",
        {"change_type": ChangeSetType.ITERATION},
        format="json",
    )
    # Permission denial is returned as 404 to avoid leaking object existence.
    assert response.status_code == 404
    assert not ProductChangeSet.objects.filter(
        product=active_product,
        change_type=ChangeSetType.ITERATION,
    ).exists()


@pytest.mark.django_db
def test_create_change_set_writes_audit_event(
    api_client: APIClient,
    product_manager: User,
    active_product: ProductAsset,
) -> None:
    api_client.force_authenticate(user=product_manager)
    response = api_client.post(
        f"/api/v1/products/{active_product.public_id}/change-sets",
        {"change_type": ChangeSetType.ITERATION},
        format="json",
    )
    assert response.status_code == 201
    change_set_public_id = response.json()["public_id"]
    assert AuditEvent.objects.filter(
        action_code="product_draft.create",
        resource_type="product_change_set",
        resource_public_id=change_set_public_id,
    ).exists()
