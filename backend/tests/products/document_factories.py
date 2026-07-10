"""Controlled document fixtures for product material tests."""

from __future__ import annotations

from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User


def build_controlled_document_version(
    *,
    organization: Organization,
    uploaded_by: User,
    document_code: str = "NUTRITION-LABEL",
) -> DocumentVersion:
    file_object = FileObject.objects.create(
        organization=organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=f"products/{document_code}.pdf",
        size_bytes=1024,
        sha256="a" * 64,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    document = Document.objects.create(
        organization=organization,
        document_code=document_code,
        title="Nutrition label",
        category="LABEL",
        source=DocumentSource.PRODUCT,
        status=DocumentStatus.ACTIVE,
    )
    return DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename=f"{document_code}.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.CONTROLLED,
        uploaded_by=uploaded_by,
        uploaded_at=timezone.now(),
        controlled_at=timezone.now(),
    )
