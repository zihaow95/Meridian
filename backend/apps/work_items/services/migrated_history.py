"""Public work_items services for migration history materialization."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from apps.documents.storage.base import FileStorage, StorageMoveFailed
from apps.identity.models.department import Department
from apps.identity.models.user import User
from apps.projects.errors import MigrationImportFailed
from apps.projects.models import Project, ProjectStage
from apps.work_items.models import (
    Deliverable,
    DeliverableRevision,
    DeliverableRevisionStatus,
    DeliverableStatus,
    DeliverableTier,
    Task,
    TaskSourceType,
    TaskStatus,
)


def _decode_history_file_content(item: dict[str, Any]) -> bytes:
    """Extract the real bytes for a migrated history file.

    A migrated file must ship auditable content so a checksummed storage object
    can be written. Missing/empty content fails closed rather than fabricating a
    zero-hash ACTIVE file.
    """

    raw = item.get("content_base64")
    if raw is not None:
        try:
            return base64.b64decode(str(raw), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MigrationImportFailed(
                message="Migrated history file content_base64 is not valid base64."
            ) from exc
    text = item.get("content_text")
    if text is not None:
        return str(text).encode("utf-8")
    content = item.get("content")
    if isinstance(content, bytes | bytearray):
        return bytes(content)
    raise MigrationImportFailed(
        message=(
            "Migrated history file requires real content "
            "(content_base64/content_text) to write a storage object."
        )
    )


def create_migrated_history_task(
    *,
    project: Project,
    stage: ProjectStage,
    item: dict[str, Any],
    department: Department,
) -> Task:
    """Create a completed history task owned by work_items (migration path)."""

    task_code = str(item.get("task_code") or f"HIST-{uuid4().hex[:8]}")
    existing = Task.objects.filter(project=project, task_code=task_code).first()
    if existing is not None:
        return existing
    return Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code=task_code,
        name=str(item.get("name") or "Migrated history task"),
        description=f"Migrated from stage {item.get('stage_code', '')}",
        source_type=TaskSourceType.MIGRATED_HISTORY,
        is_core=False,
        responsible_department=department,
        status=TaskStatus.COMPLETED,
        version_no=1,
    )


def create_migrated_history_deliverable(
    *,
    project: Project,
    stage: ProjectStage,
    item: dict[str, Any],
    actor: User,
    storage: FileStorage,
) -> Deliverable:
    """Create a history deliverable bound to a real, checksummed storage object.

    Follows the state-compensated file pipeline: write bytes to the isolated temp
    dir, compute SHA-256, create a PENDING file object, atomically move to the
    final object key, then mark ACTIVE/CONTROLLED only after the move succeeds.
    """

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    code = str(item.get("deliverable_code") or f"MIG-FILE-{uuid4().hex[:10]}")
    existing = Deliverable.objects.filter(project=project, deliverable_code=code).first()
    if existing is not None:
        return existing

    source_note = str(item.get("source_note") or "Migrated history file")
    source_version = str(item.get("source_version") or item.get("migration_source_version") or "1")
    mime = str(item.get("mime_type") or "application/octet-stream")

    content = _decode_history_file_content(item)
    if not content:
        raise MigrationImportFailed(message="Migrated history file content is empty.")
    sha256 = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    object_key = f"{uuid4()}/{uuid4()}"

    temp_path = storage.temp_dir() / f"{uuid4()}.part"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(content)

    now = timezone.now()
    file_object = FileObject.objects.create(
        organization=project.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=object_key,
        size_bytes=size_bytes,
        sha256=sha256,
        detected_mime_type=mime,
        storage_status=StorageStatus.PENDING,
    )
    document = Document.objects.create(
        organization=project.organization,
        document_code=f"MIG-{uuid4().hex[:12].upper()}",
        title=filename,
        source=DocumentSource.MIGRATION,
        category="MIGRATION_HISTORY",
    )
    version = DocumentVersion.objects.create(
        organization=project.organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename=filename,
        declared_mime_type=mime,
        detected_mime_type=mime,
        status=VersionStatus.DRAFT,
        uploaded_by=actor,
        uploaded_at=now,
        sensitivity_level="INTERNAL",
    )
    try:
        storage.atomic_move(Path(temp_path), object_key)
    except StorageMoveFailed as exc:
        temp_path.unlink(missing_ok=True)
        raise MigrationImportFailed(
            message=f"Failed to persist migrated history file: {filename}"
        ) from exc

    file_object.storage_status = StorageStatus.ACTIVE
    file_object.save(update_fields=["storage_status"])
    version.status = VersionStatus.CONTROLLED
    version.controlled_at = now
    version.save(update_fields=["status", "controlled_at"])
    document.current_version = version
    document.save(update_fields=["current_version"])

    deliverable = Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        deliverable_code=code,
        name=filename,
        tier=DeliverableTier.PROJECT_CUSTOM,
        status=DeliverableStatus.CONTROLLED,
        requires_professional_confirmation=False,
        exemption_reason=f"{source_note}; source_version={source_version}",
    )
    revision = DeliverableRevision.objects.create(
        organization=project.organization,
        deliverable=deliverable,
        revision_number=1,
        document_version=version,
        status=DeliverableRevisionStatus.CONTROLLED,
        content_hash=sha256,
        submitted_by=actor,
        submitted_at=now,
        locked_at=now,
    )
    deliverable.current_revision = revision
    deliverable.save(update_fields=["current_revision", "updated_at"])
    return deliverable
