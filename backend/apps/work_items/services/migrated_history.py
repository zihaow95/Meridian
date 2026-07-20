"""Public work_items services for migration history materialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from django.utils import timezone

from apps.documents.models import DocumentSource, DocumentVersion, StorageStatus, VersionStatus
from apps.documents.services.ingest import StagedContent, stage_controlled_content
from apps.documents.storage.base import FileStorage
from apps.identity.models.department import Department
from apps.identity.models.user import User
from apps.projects.errors import MigrationImportFailed
from apps.projects.models import Project, ProjectStage
from apps.projects.services.migration_file_staging import resolve_migration_staging_path
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


@dataclass(frozen=True)
class MigratedFileStage:
    """PENDING staged file plus the metadata needed to attach a deliverable later."""

    staged: StagedContent
    filename: str
    deliverable_code: str
    source_note: str
    source_version: str
    sha256: str
    version_public_id: str


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


def stage_migrated_history_file(
    *,
    project: Project,
    item: dict[str, Any],
    actor: User,
    storage: FileStorage,
) -> MigratedFileStage | None:
    """Stage a migrated history file as PENDING without creating a business reference.

    Bytes must already live on the storage temp dir (``staging_relpath`` from import).
    This never loads Base64 from MySQL and never marks a deliverable CONTROLLED.
    """

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    code = str(item.get("deliverable_code") or f"MIG-FILE-{uuid4().hex[:10]}")
    existing = Deliverable.objects.filter(project=project, deliverable_code=code).first()
    if existing is not None and existing.current_revision_id is not None:
        return None

    pending_version_public_id = item.get("pending_version_public_id")
    if pending_version_public_id:
        version = (
            DocumentVersion.objects.filter(
                public_id=pending_version_public_id,
                organization_id=project.organization_id,
            )
            .select_related("file_object")
            .first()
        )
        if version is not None:
            return MigratedFileStage(
                staged=StagedContent(
                    version_id=version.id,
                    file_object_id=version.file_object_id,
                    temp_path=storage.temp_dir() / "unused",
                    object_key=version.file_object.object_key,
                ),
                filename=filename,
                deliverable_code=code,
                source_note=str(item.get("source_note") or "Migrated history file"),
                source_version=str(
                    item.get("source_version") or item.get("migration_source_version") or "1"
                ),
                sha256=str(item.get("sha256") or version.file_object.sha256),
                version_public_id=str(version.public_id),
            )

    staging_relpath = item.get("staging_relpath")
    if not staging_relpath:
        raise MigrationImportFailed(
            message=(
                "Migrated history file requires a staged storage payload "
                "(staging_relpath) before confirmation."
            )
        )
    temp_path = resolve_migration_staging_path(storage, str(staging_relpath))
    if not temp_path.is_file():
        raise MigrationImportFailed(
            message=f"Staged migration file missing on disk: {staging_relpath}"
        )

    sha256 = str(item.get("sha256") or "")
    size_bytes = int(item.get("size_bytes") or 0)
    if not sha256 or size_bytes <= 0:
        raise MigrationImportFailed(
            message="Migrated history file staging metadata (sha256/size_bytes) is required."
        )

    mime = str(item.get("mime_type") or "application/octet-stream")
    source_note = str(item.get("source_note") or "Migrated history file")
    source_version = str(item.get("source_version") or item.get("migration_source_version") or "1")

    version, staged = stage_controlled_content(
        organization=project.organization,
        source_temp_path=temp_path,
        sha256=sha256,
        size_bytes=size_bytes,
        original_filename=filename,
        mime_type=mime,
        uploaded_by=actor,
        source=DocumentSource.MIGRATION,
        category="MIGRATION_HISTORY",
        document_code=f"MIG-{uuid4().hex[:12].upper()}",
        title=filename,
    )
    return MigratedFileStage(
        staged=staged,
        filename=filename,
        deliverable_code=code,
        source_note=source_note,
        source_version=source_version,
        sha256=sha256,
        version_public_id=str(version.public_id),
    )


def attach_migrated_history_deliverable(
    *,
    project: Project,
    stage: ProjectStage,
    version: DocumentVersion,
    filename: str,
    deliverable_code: str,
    source_note: str,
    source_version: str,
    sha256: str,
    actor: User,
) -> Deliverable:
    """Bind a CONTROLLED deliverable only after the file version is ACTIVE."""

    version.refresh_from_db()
    file_object = version.file_object
    if (
        version.status != VersionStatus.CONTROLLED
        or file_object.storage_status != StorageStatus.ACTIVE
    ):
        raise MigrationImportFailed(
            message="Only ACTIVE/CONTROLLED document versions may be referenced by deliverables."
        )

    existing = Deliverable.objects.filter(
        project=project, deliverable_code=deliverable_code
    ).first()
    now = timezone.now()
    if existing is not None:
        if existing.current_revision_id is not None:
            return existing
        revision = DeliverableRevision.objects.create(
            organization=project.organization,
            deliverable=existing,
            revision_number=1,
            document_version=version,
            status=DeliverableRevisionStatus.CONTROLLED,
            content_hash=sha256,
            submitted_by=actor,
            submitted_at=now,
            locked_at=now,
        )
        existing.current_revision = revision
        existing.status = DeliverableStatus.CONTROLLED
        existing.exemption_reason = f"{source_note}; source_version={source_version}"
        existing.save(
            update_fields=["current_revision", "status", "exemption_reason", "updated_at"]
        )
        return existing

    deliverable = Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        deliverable_code=deliverable_code,
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
