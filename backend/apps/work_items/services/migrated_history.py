"""Public work_items services for migration history materialization."""

from __future__ import annotations

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
from apps.identity.models.department import Department
from apps.identity.models.user import User
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
) -> Deliverable:
    """Create a history deliverable bound to a real FileObject/DocumentVersion."""

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    code = str(item.get("deliverable_code") or f"MIG-FILE-{uuid4().hex[:10]}")
    existing = Deliverable.objects.filter(project=project, deliverable_code=code).first()
    if existing is not None:
        return existing

    source_note = str(item.get("source_note") or "Migrated history file")
    source_version = str(item.get("source_version") or item.get("migration_source_version") or "1")
    sha256 = str(item.get("sha256") or ("0" * 64))
    size_bytes = int(item.get("size_bytes") or 0)
    mime = str(item.get("mime_type") or "application/octet-stream")
    object_key = str(
        item.get("object_key") or f"migration/{project.public_id}/{uuid4()}/{filename}"
    )

    now = timezone.now()
    file_object = FileObject.objects.create(
        organization=project.organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=object_key,
        size_bytes=size_bytes,
        sha256=sha256,
        detected_mime_type=mime,
        storage_status=StorageStatus.ACTIVE,
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
        status=VersionStatus.CONTROLLED,
        uploaded_by=actor,
        uploaded_at=now,
        controlled_at=now,
        sensitivity_level="INTERNAL",
    )
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
