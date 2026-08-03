"""Repair seed must upgrade forged labels without overwriting material history."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest
from django.conf import settings
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.management.commands.seed_e2e_user import Command as SeedE2ECommand
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.products.models import (
    AttributeOwnerType,
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductMaterial,
    ProductSourceType,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def yogurt_product(organization: Organization, active_user: User) -> ProductAsset:
    return ProductAsset.objects.create(
        organization=organization,
        business_no="E2E-REPAIR-LABEL",
        name="Repair Label Product",
        category_code="YOGURT",
        source_type=ProductSourceType.LEGACY_IMPORT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )


def _forged_document(
    *,
    organization: Organization,
    actor: User,
    marker: str,
) -> DocumentVersion:
    storage_root = settings.FILE_STORAGE_ROOT
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = f"forged-{marker}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    document = Document.objects.create(
        organization_id=organization.id,
        document_code=f"FORGED-{marker}",
        title=f"Forged {marker}",
        source=DocumentSource.PRODUCT,
    )
    object_key = f"e2e/forged/{marker}.bin"
    file_object = FileObject.objects.create(
        organization_id=organization.id,
        object_key=object_key,
        storage_backend=StorageBackend.NAS_NFS,
        size_bytes=len(payload),
        sha256=digest,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    (storage_root / object_key).parent.mkdir(parents=True, exist_ok=True)
    (storage_root / object_key).write_bytes(payload)
    return DocumentVersion.objects.create(
        organization_id=organization.id,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename=f"{marker}.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.CONTROLLED,
        catalog_item_code="PRODUCT_LABEL",
        uploaded_by=actor,
        uploaded_at=timezone.now(),
    )


def test_repair_seed_upgrades_forged_live_approval_without_overwriting_history(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="live",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.APPROVED,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash="0" * 64,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.APPROVED,
        decided_at=timezone.now(),
        live_slot=1,
    )

    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    old.refresh_from_db()
    assert old.document_version_id == forged_version.id
    assert old.current_slot is None
    assert old.material_status == MaterialStatus.INACTIVE
    assert not MaterialConfirmation.objects.filter(material=old, live_slot=1).exists()

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    assert current.pk != old.pk
    assert current.version_no == 2
    assert current.document_version_id != forged_version.id
    assert SeedE2ECommand()._has_valid_approved_confirmation(current)


def test_repair_seed_upgrades_stale_pending_confirmation_on_rerun(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="pending",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.DRAFT,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    stale_pending = MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash=forged_version.file_object.sha256,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.PENDING,
    )

    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    stale_pending.refresh_from_db()
    assert stale_pending.superseded_at is not None
    old.refresh_from_db()
    assert old.document_version_id == forged_version.id
    assert old.current_slot is None

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    assert current.pk != old.pk
    assert SeedE2ECommand()._has_valid_approved_confirmation(current)
