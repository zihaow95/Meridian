"""Query helpers for migration staging paths still awaiting confirmation."""

from __future__ import annotations

from apps.projects.models import MigrationBaseline, MigrationBaselineStatus


def referenced_migration_staging_relpaths() -> set[str]:
    """Return staging_relpath values still referenced by IMPORTED baselines."""

    names: set[str] = set()
    for baseline in MigrationBaseline.objects.filter(
        status=MigrationBaselineStatus.IMPORTED
    ).iterator():
        for item in list(baseline.history_files or []) + list(baseline.history_deliverables or []):
            if isinstance(item, dict) and item.get("staging_relpath"):
                names.add(str(item["staging_relpath"]))
    return names
