"""Storage reconciliation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.documents.models import FileObject, StorageBackend, StorageStatus
from apps.documents.services.reconcile import ReconcileStorage
from apps.documents.services.uploads import complete_upload


@pytest.mark.django_db
def test_reconcile_marks_missing_active_files(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    path = file_storage.final_path_for(version.file_object.object_key)
    path.unlink()
    result = ReconcileStorage(storage=file_storage).execute()
    version.file_object.refresh_from_db()
    assert result["marked_missing"] == 1
    assert version.file_object.storage_status == StorageStatus.MISSING


@pytest.mark.django_db
def test_reconcile_completes_pending_object_when_formal_file_exists(
    file_storage, active_user
) -> None:
    """PENDING + formal object on disk must be activated, not skipped."""

    from apps.documents.models import (
        Document,
        DocumentSource,
        DocumentVersion,
        VersionStatus,
    )
    from apps.documents.services.ingest import complete_pending_file_activation

    file_object = FileObject.objects.create(
        organization=active_user.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key="orphan/moved-but-pending",
        size_bytes=10,
        sha256="0" * 64,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.PENDING,
    )
    document = Document.objects.create(
        organization=active_user.organization,
        document_code="DOC-PENDING-ACTIVATE",
        title="pending.pdf",
        source=DocumentSource.PROJECT,
    )
    DocumentVersion.objects.create(
        organization=active_user.organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename="pending.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.DRAFT,
        uploaded_by=active_user,
        uploaded_at=timezone.now(),
    )
    path = file_storage.final_path_for(file_object.object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0123456789")

    result = ReconcileStorage(storage=file_storage).execute()
    file_object.refresh_from_db()
    assert result["pending_activated"] == 1
    assert file_object.storage_status == StorageStatus.ACTIVE
    version = complete_pending_file_activation(file_object)
    assert version is not None
    assert version.status == VersionStatus.CONTROLLED


@pytest.mark.django_db
def test_reconcile_sweeps_stale_pending_object_without_backing_file(
    file_storage, active_user
) -> None:
    """A staged object whose activation never completed is compensated."""

    file_object = FileObject.objects.create(
        organization=active_user.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key="orphan/never-activated",
        size_bytes=10,
        sha256="0" * 64,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.PENDING,
    )
    FileObject.objects.filter(id=file_object.id).update(
        created_at=timezone.now() - timedelta(hours=5)
    )

    result = ReconcileStorage(storage=file_storage, pending_timeout_minutes=60).execute()

    file_object.refresh_from_db()
    assert result["pending_swept"] == 1
    assert file_object.storage_status == StorageStatus.MISSING
