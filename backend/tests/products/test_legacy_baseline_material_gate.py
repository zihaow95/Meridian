"""A legacy baseline may not go live on unconfirmed or missing materials.

Publishing used to check only the product name. The rule the pilot needs is
stronger: whatever the requirements configuration marks REQUIRED for this
category must exist as the current material and carry a professional's
confirmation. Files still sitting in the triage queue are progress, not
evidence, and must not let a product through.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from django.utils import timezone

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
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductChangeSet,
    ProductVersion,
)
from apps.products.services.create_legacy_baseline import CreateLegacyBaselineDraft
from apps.products.services.publish_legacy_baseline import PublishLegacyBaseline
from apps.products.services.validate_publication import ValidateProductPublication

pytestmark = pytest.mark.django_db

MATERIAL_TYPE = "PRODUCT_LABEL"
PAYLOAD: dict[str, Any] = {
    "name": "老酸奶 200g",
    "category_code": "YOGURT",
    "business_no": "LEG-GATE-0001",
    "sku_code": "SKU-GATE-0001",
    "barcode": "6900000000009",
    "specification": "200g/杯",
}


@pytest.fixture
def director(product_director: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        product_director, "product.publish_baseline", "product", role_code="PRODUCT_DIRECTOR"
    )
    return product_director


@pytest.fixture
def baseline(director: User) -> ProductChangeSet:
    return (
        CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(director),
            payload=PAYLOAD,
            idempotency_key="gate-1",
        )
        .execute()
        .change_set
    )


@pytest.fixture
def requirements(organization: Organization, active_user: User) -> Callable[..., Any]:
    definition, _ = ConfigurationDefinition.objects.get_or_create(
        organization=organization,
        definition_code=PRODUCT_MATERIAL_REQUIREMENTS_CODE,
        defaults={"name": "产品材料要求", "description": ""},
    )

    def _publish(requirement: str = "REQUIRED") -> ConfigurationVersion:
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
                        "lifecycle_state": "ACTIVE",
                        "materials": [
                            {"material_type_code": MATERIAL_TYPE, "requirement": requirement}
                        ],
                    }
                ]
            },
            created_by=active_user,
            published_at=timezone.now(),
        )

    return _publish


@pytest.fixture
def controlled_version(
    organization: Organization, active_user: User
) -> Callable[..., DocumentVersion]:
    storage = get_file_storage()

    def _create() -> DocumentVersion:
        content = f"%PDF-1.4 {uuid4()}".encode()
        temp_path = storage.temp_dir() / f"{uuid4()}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            original_filename="label.pdf",
            mime_type="application/pdf",
            uploaded_by=active_user,
            source=DocumentSource.MIGRATION,
            catalog_item_code=MATERIAL_TYPE,
        )
        return activate_staged_content(staged, storage)

    return _create


def add_material(baseline: ProductChangeSet, version: DocumentVersion, *, status: str) -> Any:
    from apps.products.models import ProductMaterial

    return ProductMaterial.objects.create(
        organization=baseline.organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=baseline.product_id,
        material_type_code=MATERIAL_TYPE,
        document_version=version,
        material_status=status,
        version_no=1,
        current_slot=1,
    )


def publish(director: User, baseline: ProductChangeSet) -> Any:
    return PublishLegacyBaseline(
        context=CommandContext.for_actor(director),
        baseline_public_id=baseline.public_id,
        idempotency_key="publish-gate-1",
    ).execute()


def block_codes(director: User, baseline: ProductChangeSet) -> set[str]:
    result = ValidateProductPublication(
        actor=director, change_set_public_id=baseline.public_id
    ).execute()
    return {block.code for block in result.blocks}


def test_publication_is_blocked_when_a_required_material_is_missing(
    director: User, baseline: ProductChangeSet, requirements
) -> None:
    requirements()

    with pytest.raises(ValidationFailedError) as excinfo:
        publish(director, baseline)

    assert "PRODUCT_MATERIAL_INCOMPLETE" in excinfo.value.details["blocks"]
    assert ProductVersion.objects.count() == 0


def test_publication_is_blocked_while_the_material_awaits_confirmation(
    director: User, baseline: ProductChangeSet, requirements, controlled_version
) -> None:
    requirements()
    add_material(baseline, controlled_version(), status=MaterialStatus.DRAFT)

    assert "PRODUCT_MATERIAL_NOT_CONFIRMED" in block_codes(director, baseline)


def test_a_file_waiting_in_the_triage_queue_does_not_unblock_publication(
    director: User,
    baseline: ProductChangeSet,
    requirements,
    controlled_version,
    organization: Organization,
    active_user: User,
) -> None:
    requirements()
    LegacyMaterialSubmission.objects.create(
        organization=organization,
        document_version=controlled_version(),
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=baseline.product_id,
        submitted_by=active_user,
        sha256="d" * 64,
        idempotency_key="queued-1",
        processing_status=LegacyMaterialStatus.PENDING_TRIAGE,
    )

    with pytest.raises(ValidationFailedError) as excinfo:
        publish(director, baseline)

    assert "PRODUCT_MATERIAL_PENDING_TRIAGE" in excinfo.value.details["blocks"]
    assert ProductVersion.objects.count() == 0


def test_a_confirmed_current_material_lets_the_baseline_publish(
    director: User, baseline: ProductChangeSet, requirements, controlled_version
) -> None:
    requirements()
    add_material(baseline, controlled_version(), status=MaterialStatus.APPROVED)

    result = publish(director, baseline)

    baseline.refresh_from_db()
    assert result.product_version.pk is not None
    assert baseline.product.lifecycle_status == "ACTIVE"


def test_an_optional_material_does_not_block_the_baseline(
    director: User, baseline: ProductChangeSet, requirements
) -> None:
    requirements(requirement="OPTIONAL")

    result = publish(director, baseline)

    assert result.product_version.pk is not None


def test_without_published_requirements_there_is_nothing_to_enforce(
    director: User, baseline: ProductChangeSet
) -> None:
    """Absence of configuration means no requirement was declared, not a silent pass."""

    result = publish(director, baseline)

    assert result.product_version.pk is not None
    assert not any(code.startswith("PRODUCT_MATERIAL") for code in block_codes(director, baseline))


def test_the_legacy_path_uses_the_shared_validator_for_core_fields(
    director: User, baseline: ProductChangeSet
) -> None:
    baseline.product.name = ""
    baseline.product.save(update_fields=["name"])

    with pytest.raises(ValidationFailedError) as excinfo:
        publish(director, baseline)

    assert "PRODUCT_REQUIRED_FIELD_MISSING" in excinfo.value.details["blocks"]


def test_a_blocked_publication_leaves_the_change_set_untouched(
    director: User, baseline: ProductChangeSet, requirements
) -> None:
    requirements()

    with pytest.raises(ValidationFailedError):
        publish(director, baseline)

    baseline.refresh_from_db()
    assert baseline.status == "DRAFT"
    assert baseline.published_at is None
    assert baseline.publish_idempotency_key == ""


def test_publication_can_be_retried_after_the_material_is_confirmed(
    director: User, baseline: ProductChangeSet, requirements, controlled_version
) -> None:
    requirements()
    material = add_material(baseline, controlled_version(), status=MaterialStatus.DRAFT)
    with pytest.raises(ValidationFailedError):
        publish(director, baseline)

    material.material_status = MaterialStatus.APPROVED
    material.save(update_fields=["material_status"])
    result = publish(director, baseline)

    assert result.product_version.pk is not None
    assert ProductVersion.objects.count() == 1
