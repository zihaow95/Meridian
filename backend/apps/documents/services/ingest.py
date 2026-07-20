"""Public documents pipeline for creating controlled file objects.

This is the single place that turns staged bytes into a CONTROLLED
``DocumentVersion``. Both interactive uploads and migration import route
through here so no other domain writes ``FileObject`` / ``Document`` /
``DocumentVersion`` directly.

The pipeline is deliberately two-phase so it is durable against partial
failures:

* :func:`stage_controlled_content` creates the PENDING database rows inside the
  caller's transaction and leaves the payload in the isolated temp directory.
* :func:`activate_staged_content` performs the physical storage move and flips
  the objects to ACTIVE/CONTROLLED. Callers run it **after** their transaction
  commits, so a later database failure that rolls the transaction back never
  leaves an orphaned formal object behind. If activation itself fails the
  objects stay PENDING and :class:`ReconcileStorage` compensates them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.documents.storage.base import FileStorage, StorageMoveFailed
from apps.identity.models.organization import Organization
from apps.identity.models.user import User


class ControlledIngestFailed(Exception):
    """Raised when a staged controlled file cannot be persisted."""


@dataclass(frozen=True)
class StagedContent:
    """Handle for a staged (PENDING) controlled file awaiting activation."""

    version_id: int
    file_object_id: int
    document_id: int
    temp_path: Path
    object_key: str
    version_public_id: str


def stage_controlled_content(
    *,
    organization: Organization,
    source_temp_path: Path,
    sha256: str,
    size_bytes: int,
    original_filename: str,
    mime_type: str,
    uploaded_by: User,
    source: str,
    category: str = "",
    document_code: str | None = None,
    title: str | None = None,
    sensitivity_level: str = "INTERNAL",
) -> tuple[DocumentVersion, StagedContent]:
    """Create PENDING file/document/version rows for an already-staged payload.

    ``source_temp_path`` must already contain the bytes (written by the caller
    into ``storage.temp_dir()``). No storage move happens here.
    """

    if size_bytes <= 0:
        raise ControlledIngestFailed("Controlled content must not be empty.")

    now = timezone.now()
    object_key = f"{uuid4()}/{uuid4()}"
    file_object = FileObject.objects.create(
        organization=organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=object_key,
        size_bytes=size_bytes,
        sha256=sha256,
        detected_mime_type=mime_type,
        storage_status=StorageStatus.PENDING,
    )
    document = Document.objects.create(
        organization=organization,
        document_code=document_code or f"DOC-{uuid4().hex[:12].upper()}",
        title=title or original_filename,
        source=source,
        category=category,
    )
    version = DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename=original_filename,
        declared_mime_type=mime_type,
        detected_mime_type=mime_type,
        status=VersionStatus.DRAFT,
        uploaded_by=uploaded_by,
        uploaded_at=now,
        sensitivity_level=sensitivity_level,
    )
    staged = StagedContent(
        version_id=version.id,
        file_object_id=file_object.id,
        document_id=document.id,
        temp_path=Path(source_temp_path),
        object_key=object_key,
        version_public_id=str(version.public_id),
    )
    return version, staged


def activate_staged_content(staged: StagedContent, storage: FileStorage) -> DocumentVersion:
    """Move the staged payload into permanent storage and mark it controlled.

    Runs after the staging transaction commits. On move failure the temp file is
    removed and the PENDING rows are left for reconciliation.
    """

    file_object = FileObject.objects.get(id=staged.file_object_id)
    version = DocumentVersion.objects.select_related("document").get(id=staged.version_id)

    try:
        storage.atomic_move(staged.temp_path, staged.object_key)
    except StorageMoveFailed:
        # Leave the PENDING rows for reconciliation and surface the storage
        # failure unchanged so callers keep their existing contract.
        staged.temp_path.unlink(missing_ok=True)
        raise

    now = timezone.now()
    file_object.storage_status = StorageStatus.ACTIVE
    file_object.save(update_fields=["storage_status"])
    version.status = VersionStatus.CONTROLLED
    version.controlled_at = now
    version.save(update_fields=["status", "controlled_at"])
    document = version.document
    document.current_version = version
    document.save(update_fields=["current_version"])
    return version
