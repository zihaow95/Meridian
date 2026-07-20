"""Project instance shell created after case-to-project approval."""

from __future__ import annotations

from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    label = "projects"

    def ready(self) -> None:
        from apps.documents.services.reconcile import register_protected_temp_relpath_provider
        from apps.projects.queries.migration_staging import referenced_migration_staging_relpaths

        register_protected_temp_relpath_provider(referenced_migration_staging_relpaths)
