"""Public documents pipeline for creating controlled file objects.

This is the single place that turns staged bytes into a CONTROLLED
``DocumentVersion``. Both interactive uploads and migration import route
through here so no other domain writes ``FileObject`` / ``Document`` /
``DocumentVersion`` directly.

The pipeline is deliberately two-phase so it is durable against partial
failures:

* :func:`stage_controlled_content` creates the PENDING database rows inside the
  caller's transaction and leaves the payload in the isolated temp directory.
* :func:`activate_staged_content` performs the physical storage move, then flips
  PENDING→ACTIVE / DRAFT→CONTROLLED in **one** database transaction. Callers run
  it **after** their staging transaction commits. If the move succeeds but the
  database update fails, the formal object remains on disk with a PENDING row and
  :func:`complete_pending_file_activation` / :class:`ReconcileStorage` finish it.
* Business objects must only reference versions after activation (ACTIVE file +
  CONTROLLED version).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.db import transaction
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
    temp_path: Path
    object_key: str


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
        temp_path=Path(source_temp_path),
        object_key=object_key,
    )
    return version, staged


def complete_pending_file_activation(file_object: FileObject) -> DocumentVersion | None:
    """Mark a PENDING file ACTIVE when its formal object already exists on disk.

    Used by reconcile (and idempotent retries) when the storage move succeeded
    but the subsequent database activation did not.
    """

    if file_object.storage_status != StorageStatus.PENDING:
        version = (
            DocumentVersion.objects.select_related("document")
            .filter(file_object=file_object)
            .order_by("-version_number")
            .first()
        )
        return version

    now = timezone.now()
    with transaction.atomic():
        locked = FileObject.objects.select_for_update().get(id=file_object.id)
        if locked.storage_status != StorageStatus.PENDING:
            return (
                DocumentVersion.objects.select_related("document")
                .filter(file_object=locked)
                .order_by("-version_number")
                .first()
            )
        version = (
            DocumentVersion.objects.select_for_update()
            .select_related("document")
            .filter(file_object=locked)
            .order_by("-version_number")
            .first()
        )
        if version is None:
            return None
        locked.storage_status = StorageStatus.ACTIVE
        locked.save(update_fields=["storage_status"])
        version.status = VersionStatus.CONTROLLED
        version.controlled_at = now
        version.save(update_fields=["status", "controlled_at"])
        document = version.document
        document.current_version = version
        document.save(update_fields=["current_version"])
        return version


def activate_pending_version(*, version_id: int, storage: FileStorage) -> DocumentVersion:
    """Public recovery: finish activation for a known PENDING document version."""

    version = DocumentVersion.objects.select_related("document", "file_object").get(id=version_id)
    file_object = version.file_object
    final_path = storage.final_path_for(file_object.object_key)
    if file_object.storage_status == StorageStatus.ACTIVE and final_path.exists():
        return version
    if not final_path.exists():
        raise ControlledIngestFailed(
            "Pending migration file has no formal storage object to activate."
        )
    activated = complete_pending_file_activation(file_object)
    if activated is None:
        raise ControlledIngestFailed("Pending file object has no document version to activate.")
    return activated


def activate_staged_content(staged: StagedContent, storage: FileStorage) -> DocumentVersion:
    """Move the staged payload into permanent storage and mark it controlled.

    Runs after the staging transaction commits. The move happens first; database
    activation is a single atomic block. On move failure the temp file is removed
    and the PENDING rows are left for reconciliation. On database failure after a
    successful move, the formal object remains and
    :func:`complete_pending_file_activation` recovers it.
    """

    file_object = FileObject.objects.get(id=staged.file_object_id)
    final_path = storage.final_path_for(staged.object_key)

    if file_object.storage_status == StorageStatus.ACTIVE and final_path.exists():
        version = DocumentVersion.objects.select_related("document").get(id=staged.version_id)
        return version

    if not final_path.exists():
        try:
            storage.atomic_move(staged.temp_path, staged.object_key)
        except StorageMoveFailed:
            staged.temp_path.unlink(missing_ok=True)
            raise
    else:
        staged.temp_path.unlink(missing_ok=True)

    activated = complete_pending_file_activation(file_object)
    if activated is None:
        raise ControlledIngestFailed("Pending file object has no document version to activate.")
    return activated
