"""Query helpers for migration staging paths still awaiting durable activation."""

from __future__ import annotations

from apps.projects.models import MigrationBaseline
from apps.projects.services.migration_file_staging import active_migration_staging_relpaths


def referenced_migration_staging_relpaths() -> set[str]:
    """Return staging paths that must survive reconcile cleanup.

    Includes durable ``MigrationFileStage`` handles that are still claimable or
    claimed-but-unconsumed, plus any baseline JSON that still references a path
    (CONFIRMED window before activation finishes).
    """

    names = active_migration_staging_relpaths()
    for baseline in MigrationBaseline.objects.iterator():
        for item in list(baseline.history_files or []) + list(baseline.history_deliverables or []):
            if isinstance(item, dict) and item.get("staging_relpath"):
                names.add(str(item["staging_relpath"]).replace("\\", "/"))
    return names
