"""Project API routes."""

from __future__ import annotations

from django.urls import path

from apps.projects.api.migrations import (
    ProjectMigrationBaselineConfirmView,
    ProjectMigrationBatchCreateView,
)
from apps.projects.api.workbench import (
    ProjectDeliverablesCollectionView,
    ProjectEmergencyExecutionsView,
    ProjectListView,
    ProjectPlanChangesView,
    ProjectStagesView,
    ProjectTasksCollectionView,
    ProjectWorkbenchDetailView,
)

urlpatterns = [
    path("projects", ProjectListView.as_view(), name="projects-list"),
    path(
        "projects/<uuid:public_id>",
        ProjectWorkbenchDetailView.as_view(),
        name="project-detail",
    ),
    path(
        "projects/<uuid:public_id>/stages",
        ProjectStagesView.as_view(),
        name="project-stages",
    ),
    path(
        "projects/<uuid:public_id>/tasks",
        ProjectTasksCollectionView.as_view(),
        name="project-tasks",
    ),
    path(
        "projects/<uuid:public_id>/deliverables",
        ProjectDeliverablesCollectionView.as_view(),
        name="project-deliverables",
    ),
    path(
        "projects/<uuid:public_id>/plan-changes",
        ProjectPlanChangesView.as_view(),
        name="project-plan-changes",
    ),
    path(
        "projects/<uuid:public_id>/emergency-executions",
        ProjectEmergencyExecutionsView.as_view(),
        name="project-emergency-executions",
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
