"""Project API routes."""

from __future__ import annotations

from django.urls import path

from apps.projects.api.migrations import (
    ProjectMigrationBaselineConfirmView,
    ProjectMigrationBatchCreateView,
    ProjectMigrationFileStageView,
)
from apps.projects.api.workbench import (
    EmergencyExecutionCompleteView,
    ExecutionExceptionConfirmView,
    PlanChangeConfirmView,
    ProjectDeliverablesCollectionView,
    ProjectEmergencyExecutionsView,
    ProjectListView,
    ProjectMembersView,
    ProjectPlanChangesView,
    ProjectPublishRepairView,
    ProjectStageHandlingRequestView,
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
        "projects/<uuid:public_id>/members",
        ProjectMembersView.as_view(),
        name="project-members",
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
        "project-stages/<uuid:public_id>/handling-requests",
        ProjectStageHandlingRequestView.as_view(),
        name="project-stage-handling-requests",
    ),
    path(
        "execution-exceptions/<uuid:public_id>/confirm",
        ExecutionExceptionConfirmView.as_view(),
        name="execution-exceptions-confirm",
    ),
    path(
        "plan-changes/<uuid:public_id>/confirm",
        PlanChangeConfirmView.as_view(),
        name="plan-changes-confirm",
    ),
    path(
        "emergency-executions/<uuid:public_id>/complete",
        EmergencyExecutionCompleteView.as_view(),
        name="emergency-executions-complete",
    ),
    path(
        "projects/<uuid:public_id>/publish-repair",
        ProjectPublishRepairView.as_view(),
        name="project-publish-repair",
    ),
    path(
        "project-migration-files/stage",
        ProjectMigrationFileStageView.as_view(),
        name="project-migration-files-stage",
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
