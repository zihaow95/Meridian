"""Activate or recover migrated history files within the projects domain."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.documents.models import DocumentVersion, StorageStatus
from apps.documents.services.ingest import (
    StagedContent,
    activate_staged_content,
    complete_pending_file_activation,
)
from apps.documents.storage.base import FileStorage
from apps.projects.errors import MigrationImportFailed
from apps.projects.services.migration_file_staging import resolve_migration_staging_path


def activate_or_recover_history_file(
    item: dict[str, Any],
    *,
    organization_id: int,
    storage: FileStorage,
) -> DocumentVersion | None:
    """Finish activation for a baseline file row, preferring staging bytes when needed.

    If ``pending_version_public_id`` was persisted before the storage move and the
    process crashed, the formal object may be missing while ``staging_relpath``
    still exists. Recovery must continue from that temp file rather than failing
    solely because the formal path is absent.
    """

    pending_raw = item.get("pending_version_public_id")
    staging_relpath = item.get("staging_relpath")
    if not pending_raw:
        return None
    try:
        pending_id = UUID(str(pending_raw))
    except ValueError as exc:
        raise MigrationImportFailed(message="Invalid pending_version_public_id.") from exc

    version = (
        DocumentVersion.objects.filter(
            public_id=pending_id,
            organization_id=organization_id,
        )
        .select_related("file_object")
        .first()
    )
    if version is None:
        return None

    file_object = version.file_object
    final_path = storage.final_path_for(file_object.object_key)
    if file_object.storage_status == StorageStatus.ACTIVE and final_path.exists():
        return version
    if final_path.exists():
        activated = complete_pending_file_activation(file_object)
        if activated is None:
            raise MigrationImportFailed(
                message="Pending migration file has no document version to activate."
            )
        return activated
    if not staging_relpath:
        raise MigrationImportFailed(
            message=(
                "Pending migration version has no formal object and no staging_relpath "
                "to resume activation."
            )
        )
    temp_path = resolve_migration_staging_path(storage, str(staging_relpath))
    if not temp_path.is_file():
        raise MigrationImportFailed(
            message=f"Staged migration file missing on disk: {staging_relpath}"
        )
    return activate_staged_content(
        StagedContent(
            version_id=version.id,
            file_object_id=file_object.id,
            temp_path=temp_path,
            object_key=file_object.object_key,
        ),
        storage,
    )
