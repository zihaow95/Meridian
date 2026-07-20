"""Query helpers for migration staging paths still awaiting durable activation."""

from __future__ import annotations

from apps.projects.models import MigrationBaseline


def referenced_migration_staging_relpaths() -> set[str]:
    """Return staging_relpath values still referenced by any baseline JSON.

    Protects both IMPORTED baselines and CONFIRMED baselines that have not yet
    finished file activation (status flips to CONFIRMED before activate runs).
    """

    names: set[str] = set()
    for baseline in MigrationBaseline.objects.iterator():
        for item in list(baseline.history_files or []) + list(baseline.history_deliverables or []):
            if isinstance(item, dict) and item.get("staging_relpath"):
                names.add(str(item["staging_relpath"]).replace("\\", "/"))
    return names
