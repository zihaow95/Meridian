"""Nutrition tables and controlled product materials."""

from __future__ import annotations

import pytest

from apps.documents.models import VersionStatus
from apps.products.models import (
    AttributeOwnerType,
    MaterialStatus,
    MaterialType,
    NutritionBasis,
    NutritionTable,
    ProductMaterial,
)
from apps.products.services.validate_publication import ValidateProductPublication
from tests.products.document_factories import build_controlled_document_version


@pytest.mark.django_db
def test_nutrition_label_mismatch_blocks_publication(
    change_set,
    controlled_label_file,
) -> None:
    NutritionTable.objects.create(
        organization=change_set.organization,
        change_set=change_set,
        basis=NutritionBasis.PER_100G,
        label_document_version=controlled_label_file,
        structured_summary_hash="structured-a",
        label_summary_hash="label-b",
    )
    result = ValidateProductPublication(
        actor=change_set.created_by,
        change_set_public_id=change_set.public_id,
    ).execute()
    assert "NUTRITION_LABEL_MISMATCH" in {block.code for block in result.blocks}


@pytest.mark.django_db
def test_non_controlled_material_blocks_publication(change_set, active_user) -> None:
    from django.utils import timezone

    from apps.documents.models import (
        Document,
        DocumentSource,
        DocumentStatus,
        DocumentVersion,
        FileObject,
        StorageBackend,
        StorageStatus,
    )

    file_object = FileObject.objects.create(
        organization=change_set.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key="products/draft-label.pdf",
        size_bytes=512,
        sha256="b" * 64,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    document = Document.objects.create(
        organization=change_set.organization,
        document_code="DRAFT-LABEL",
        title="Draft label",
        category="LABEL",
        source=DocumentSource.PRODUCT,
        status=DocumentStatus.ACTIVE,
    )
    draft_version = DocumentVersion.objects.create(
        organization=change_set.organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename="draft-label.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.DRAFT,
        uploaded_by=active_user,
        uploaded_at=timezone.now(),
    )
    ProductMaterial.objects.create(
        organization=change_set.organization,
        change_set=change_set,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=change_set.product_id,
        material_type=MaterialType.LABEL,
        document_version=draft_version,
        material_status=MaterialStatus.DRAFT,
    )
    result = ValidateProductPublication(
        actor=change_set.created_by,
        change_set_public_id=change_set.public_id,
    ).execute()
    assert "PRODUCT_MATERIAL_NOT_CONTROLLED" in {block.code for block in result.blocks}


@pytest.fixture
def controlled_label_file(organization, active_user):
    return build_controlled_document_version(organization=organization, uploaded_by=active_user)
