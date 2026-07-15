"""Project API routes."""

from __future__ import annotations

from django.urls import path

from apps.projects.api.migrations import (
    ProjectMigrationBaselineConfirmView,
    ProjectMigrationBatchCreateView,
)
from apps.projects.api.projects import ProjectDetailView

urlpatterns = [
    path(
        "projects/<uuid:public_id>",
        ProjectDetailView.as_view(),
        name="project-detail",
    ),
    path(
        "project-migration-batches",
        ProjectMigrationBatchCreateView.as_view(),
        name="project-migration-batches-create",
    ),
    path(
        "project-migration-baselines/<uuid:public_id>/confirm",
        ProjectMigrationBaselineConfirmView.as_view(),
        name="project-migration-baselines-confirm",
    ),
]
