"""Project API routes."""

from __future__ import annotations

from django.urls import path

from apps.projects.api.projects import ProjectDetailView

urlpatterns = [
    path(
        "projects/<uuid:public_id>",
        ProjectDetailView.as_view(),
        name="project-detail",
    ),
]
