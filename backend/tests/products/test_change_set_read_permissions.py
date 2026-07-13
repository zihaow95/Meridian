"""Change set detail and diff require product.read_basic on the linked product."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.products.models import ProductChangeSet
from apps.products.services.diff_change_set import BuildProductChangeSetDiff


@pytest.mark.django_db
def test_unrelated_org_peer_cannot_read_change_set_detail(
    api_client: APIClient,
    change_set: ProductChangeSet,
    ordinary_employee: User,
) -> None:
    api_client.force_authenticate(user=ordinary_employee)
    response = api_client.get(f"/api/v1/product-change-sets/{change_set.public_id}")
    # Permission denial is returned as 404 to avoid leaking object existence.
    assert response.status_code == 404


@pytest.mark.django_db
def test_product_owner_can_read_change_set_detail(
    api_client: APIClient,
    change_set: ProductChangeSet,
    product_manager: User,
) -> None:
    api_client.force_authenticate(user=product_manager)
    response = api_client.get(f"/api/v1/product-change-sets/{change_set.public_id}")
    assert response.status_code == 200
    assert response.data["public_id"] == str(change_set.public_id)


@pytest.mark.django_db
def test_unrelated_org_peer_cannot_build_change_set_diff(
    change_set: ProductChangeSet,
    ordinary_employee: User,
) -> None:
    with pytest.raises(PermissionDeniedError):
        BuildProductChangeSetDiff(
            actor=ordinary_employee,
            change_set_public_id=change_set.public_id,
        ).execute()
