"""HTTP surface for the material workbench.

Everything the workbench shows is derived from services that already enforce the
rules, so these tests are about the contract: which shapes come back, and that
the API never becomes a second, looser way in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import PRODUCT_MATERIAL_REQUIREMENTS_CODE
from apps.documents.models import DocumentSource, DocumentVersion
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialStatus,
    ProductAsset,
    ProductMaterial,
)

pytestmark = pytest.mark.django_db

MATERIAL_TYPE = "PRODUCT_LABEL"


@pytest.fixture
def staged_version(organization: Organization, active_user: User) -> Callable[..., DocumentVersion]:
    storage = get_file_storage()

    def _create(marker: str = "v1", item_code: str = MATERIAL_TYPE) -> DocumentVersion:
        content = f"%PDF-1.4 {marker}".encode()
        temp_path = storage.temp_dir() / f"{uuid4()}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            original_filename=f"{marker}.pdf",
            mime_type="application/pdf",
            uploaded_by=active_user,
            source=DocumentSource.MIGRATION,
            catalog_item_code=item_code,
        )
        return activate_staged_content(staged, storage)

    return _create


@pytest.fixture
def workbench_user(active_user: User, grant_action: Callable[..., None]) -> User:
    for action in (
        "legacy_material.submission.create",
        "legacy_material.submission.read",
        "legacy_material.submission.verify",
    ):
        grant_action(active_user, action, "legacy_material_submission")
    for action in ("product_material.manage", "product_material.completeness.read"):
        grant_action(active_user, action, "product_material")
    return active_user


@pytest.fixture
def confirmer(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(another_active_user, "product_material.confirm", "product_material")
    return another_active_user


@pytest.fixture
def client(workbench_user: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(workbench_user)
    return api


@pytest.fixture
def published_requirements(organization: Organization, active_user: User) -> ConfigurationVersion:
    definition, _ = ConfigurationDefinition.objects.get_or_create(
        organization=organization,
        definition_code=PRODUCT_MATERIAL_REQUIREMENTS_CODE,
        defaults={"name": "产品材料要求", "description": ""},
    )
    return ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        current_published_slot=1,
        content_json={
            "requirements": [
                {
                    "product_category_code": "YOGURT",
                    "lifecycle_state": "ON_SALE",
                    "materials": [
                        {"material_type_code": MATERIAL_TYPE, "requirement": "REQUIRED"},
                        {"material_type_code": "MARKETING_IMAGE", "requirement": "OPTIONAL"},
                    ],
                }
            ]
        },
        created_by=active_user,
        published_at=timezone.now(),
    )


@pytest.fixture
def product(product_asset: ProductAsset) -> ProductAsset:
    product_asset.category_code = "YOGURT"
    product_asset.save(update_fields=["category_code"])
    return product_asset


def intake(client: APIClient, product: ProductAsset, version: DocumentVersion, key: str) -> Any:
    return client.post(
        reverse("product-legacy-material-create", args=[product.public_id]),
        {
            "document_version_public_id": str(version.public_id),
            "idempotency_key": key,
            "source_note": "旧共享盘",
            "claimed_version": "V3",
        },
        format="json",
    )


def test_a_historical_file_can_be_parked_through_the_api(
    client: APIClient, product: ProductAsset, staged_version
) -> None:
    response = intake(client, product, staged_version(), "intake-1")

    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == LegacyMaterialStatus.PENDING_TRIAGE
    assert body["duplicate_candidates"] == []
    assert LegacyMaterialSubmission.objects.count() == 1


def test_the_same_idempotency_key_returns_the_same_submission(
    client: APIClient, product: ProductAsset, staged_version
) -> None:
    first = intake(client, product, staged_version(), "intake-1")
    second = intake(client, product, staged_version("v2"), "intake-1")

    assert second.json()["public_id"] == first.json()["public_id"]
    assert LegacyMaterialSubmission.objects.count() == 1


def test_the_triage_queue_lists_what_is_waiting(
    client: APIClient, product: ProductAsset, staged_version
) -> None:
    intake(client, product, staged_version(), "intake-1")

    response = client.get(reverse("product-legacy-material-list", args=[product.public_id]))

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["claimed_version"] for item in items] == ["V3"]
    assert items[0]["source_note"] == "旧共享盘"


def test_a_reader_without_the_queue_action_is_refused(
    another_active_user: User, product: ProductAsset
) -> None:
    api = APIClient()
    api.force_authenticate(another_active_user)

    response = api.get(reverse("product-legacy-material-list", args=[product.public_id]))

    # Denials read as "not found" platform-wide so a refusal never confirms that
    # the queue holds anything.
    assert response.status_code == 404


def test_verifying_and_chaining_produces_a_current_material(
    client: APIClient, product: ProductAsset, staged_version
) -> None:
    older = intake(client, product, staged_version("old"), "intake-old").json()
    newer = intake(client, product, staged_version("new"), "intake-new").json()
    for submission in (older, newer):
        verified = client.post(
            reverse("legacy-material-verify", args=[submission["public_id"]]),
            {"decision": LegacyMaterialStatus.VERIFIED, "note": "核对原件"},
            format="json",
        )
        assert verified.status_code == 200

    response = client.post(
        reverse("product-material-chain-create", args=[product.public_id]),
        {
            "material_type_code": MATERIAL_TYPE,
            "ordered_submission_ids": [older["public_id"], newer["public_id"]],
            "current_submission_id": newer["public_id"],
        },
        format="json",
    )

    assert response.status_code == 201
    chain = response.json()["items"]
    assert [item["version_no"] for item in chain] == [1, 2]
    assert [item["is_current"] for item in chain] == [False, True]


def test_the_chain_endpoint_refuses_an_unverified_submission(
    client: APIClient, product: ProductAsset, staged_version
) -> None:
    parked = intake(client, product, staged_version(), "intake-1").json()

    response = client.post(
        reverse("product-material-chain-create", args=[product.public_id]),
        {
            "material_type_code": MATERIAL_TYPE,
            "ordered_submission_ids": [parked["public_id"]],
            "current_submission_id": parked["public_id"],
        },
        format="json",
    )

    assert response.status_code == 400
    assert ProductMaterial.objects.count() == 0


def test_the_material_list_shows_the_current_version_and_its_history(
    client: APIClient, product: ProductAsset, organization: Organization, staged_version
) -> None:
    older = ProductMaterial.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=product.id,
        material_type_code=MATERIAL_TYPE,
        document_version=staged_version("old"),
        material_status=MaterialStatus.INACTIVE,
        version_no=1,
    )
    ProductMaterial.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=product.id,
        material_type_code=MATERIAL_TYPE,
        document_version=staged_version("new"),
        material_status=MaterialStatus.APPROVED,
        version_no=2,
        supersedes_material=older,
        current_slot=1,
    )

    response = client.get(reverse("product-material-list", args=[product.public_id]))

    assert response.status_code == 200
    groups = response.json()["items"]
    assert len(groups) == 1
    group = groups[0]
    assert group["material_type_code"] == MATERIAL_TYPE
    assert group["current"]["version_no"] == 2
    assert [entry["version_no"] for entry in group["history"]] == [1]
    assert "object_key" not in group["current"]


def test_completeness_reports_missing_required_materials(
    client: APIClient, product: ProductAsset, published_requirements: ConfigurationVersion
) -> None:
    response = client.get(
        reverse("product-material-completeness", args=[product.public_id]),
        {"lifecycle_state": "ON_SALE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_complete"] is False
    assert body["blocking_material_type_codes"] == [MATERIAL_TYPE]
    assert body["requirement_version_public_id"] == str(published_requirements.public_id)
    assert {item["material_type_code"] for item in body["items"]} == {
        MATERIAL_TYPE,
        "MARKETING_IMAGE",
    }


def test_completeness_is_refused_without_the_read_action(
    another_active_user: User, product: ProductAsset
) -> None:
    api = APIClient()
    api.force_authenticate(another_active_user)

    response = api.get(
        reverse("product-material-completeness", args=[product.public_id]),
        {"lifecycle_state": "ON_SALE"},
    )

    assert response.status_code == 404


def test_completeness_says_so_when_no_requirements_are_published(
    client: APIClient, product: ProductAsset
) -> None:
    response = client.get(
        reverse("product-material-completeness", args=[product.public_id]),
        {"lifecycle_state": "ON_SALE"},
    )

    assert response.status_code == 400


def test_confirmation_can_be_requested_and_decided_through_the_api(
    client: APIClient,
    product: ProductAsset,
    organization: Organization,
    staged_version,
    confirmer: User,
) -> None:
    material = ProductMaterial.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=product.id,
        material_type_code=MATERIAL_TYPE,
        document_version=staged_version(),
        version_no=1,
        current_slot=1,
    )

    requested = client.post(
        reverse("product-material-confirmation-create", args=[material.public_id]),
        {"confirmer_public_id": str(confirmer.public_id), "comment": "请确认"},
        format="json",
    )
    assert requested.status_code == 201
    assert requested.json()["decision"] == MaterialConfirmationDecision.PENDING

    confirmer_api = APIClient()
    confirmer_api.force_authenticate(confirmer)
    decided = confirmer_api.post(
        reverse("material-confirmation-decide", args=[requested.json()["public_id"]]),
        {"decision": MaterialConfirmationDecision.APPROVED, "comment": "与备案一致"},
        format="json",
    )

    assert decided.status_code == 200
    material.refresh_from_db()
    assert material.material_status == MaterialStatus.APPROVED
    assert MaterialConfirmation.objects.filter(live_slot=1).count() == 1


def test_only_the_named_confirmer_may_decide_through_the_api(
    client: APIClient,
    product: ProductAsset,
    organization: Organization,
    staged_version,
    confirmer: User,
    workbench_user: User,
) -> None:
    material = ProductMaterial.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=product.id,
        material_type_code=MATERIAL_TYPE,
        document_version=staged_version(),
        version_no=1,
        current_slot=1,
    )
    requested = client.post(
        reverse("product-material-confirmation-create", args=[material.public_id]),
        {"confirmer_public_id": str(confirmer.public_id)},
        format="json",
    )

    response = client.post(
        reverse("material-confirmation-decide", args=[requested.json()["public_id"]]),
        {"decision": MaterialConfirmationDecision.APPROVED},
        format="json",
    )

    assert response.status_code == 404
    assert MaterialConfirmation.objects.get().decision == MaterialConfirmationDecision.PENDING


def test_an_unknown_product_does_not_leak_through_the_material_list(
    client: APIClient,
) -> None:
    response = client.get(reverse("product-material-list", args=[uuid4()]))

    assert response.status_code == 404
