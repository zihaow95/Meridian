"""Public documents recovery helpers for interrupted ingest pipelines."""

from __future__ import annotations

from uuid import UUID

from apps.documents.models import DocumentVersion
from apps.documents.services.ingest import activate_pending_version
from apps.documents.storage.base import FileStorage
from apps.projects.models import MigrationBaseline


def recover_pending_migration_versions(
    *,
    baseline: MigrationBaseline,
    storage: FileStorage,
) -> list[DocumentVersion]:
    """Activate PENDING migration versions referenced by a baseline's file metadata."""

    activated: list[DocumentVersion] = []
    seen: set[str] = set()
    for item in list(baseline.history_deliverables or []) + list(baseline.history_files or []):
        if not isinstance(item, dict):
            continue
        version_public_id = item.get("pending_version_public_id")
        if not version_public_id or str(version_public_id) in seen:
            continue
        seen.add(str(version_public_id))
        try:
            public_id = UUID(str(version_public_id))
        except ValueError:
            continue
        version = DocumentVersion.objects.filter(
            public_id=public_id,
            organization_id=baseline.organization_id,
        ).first()
        if version is None:
            continue
        activated.append(activate_pending_version(version_id=version.id, storage=storage))
    return activated
