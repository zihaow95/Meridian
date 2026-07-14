"""Phase 3 acceptance: product dossier publication and legacy import."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest
from django.test import Client

from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.products.models import ProductChangeSet, ProductLifecycleStatus
from apps.products.services.import_batch import CreateProductImportBatch
from apps.products.services.import_template import sample_import_csv


@pytest.fixture
def phase3_ready_project(ready_change_set: ProductChangeSet) -> SimpleNamespace:
    return SimpleNamespace(product_change_set=ready_change_set)


@pytest.fixture
def phase3_product_director(
    product_director: User,
    grant_action: Callable[..., None],
) -> User:
    grant_action(product_director, "product.publish_new", "product", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "product.search", "product", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "migration.upload", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "migration.confirm", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(
        product_director,
        "product.publish_baseline",
        "product",
        role_code="PRODUCT_DIRECTOR",
    )
    return product_director


@pytest.fixture
def parsed_legacy_batch(phase3_product_director: User):
    return CreateProductImportBatch(
        context=CommandContext.for_actor(phase3_product_director),
        csv_content=sample_import_csv(),
        source_filename="acceptance-legacy.csv",
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_new_product_change_set_can_publish_effective_dossier(
    client: Client,
    phase3_ready_project: SimpleNamespace,
    phase3_product_director: User,
) -> None:
    client.force_login(phase3_product_director)
    change_set_id = str(phase3_ready_project.product_change_set.public_id)
    validate_response = client.post(
        f"/api/v1/product-change-sets/{change_set_id}/validate-publication",
    )
    assert validate_response.status_code == 200
    assert validate_response.json()["can_publish"] is True
    publish_response = client.post(
        f"/api/v1/product-change-sets/{change_set_id}/publish",
        data={"idempotency_key": "publish-e2e"},
        content_type="application/json",
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["product_lifecycle_status"] == ProductLifecycleStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_legacy_import_baseline_is_searchable_after_director_publish(
    client: Client,
    phase3_product_director: User,
    parsed_legacy_batch,
) -> None:
    client.force_login(phase3_product_director)
    confirm = client.post(
        f"/api/v1/product-import-batches/{parsed_legacy_batch.public_id}/confirm",
        data={"idempotency_key": "acceptance-confirm"},
        content_type="application/json",
    )
    assert confirm.status_code == 200
    baseline_id = confirm.json()["items"][0]["baseline_public_id"]
    publish = client.post(f"/api/v1/legacy-baselines/{baseline_id}/publish")
    assert publish.status_code == 200
    search = client.get("/api/v1/products", {"search": "legacy"})
    assert search.status_code == 200
    assert search.json()["items"]
