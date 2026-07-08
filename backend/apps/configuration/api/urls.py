"""Configuration API routes."""

from __future__ import annotations

from django.urls import path

from apps.configuration.api.configurations import (
    ConfigurationDefinitionListView,
    ConfigurationVersionListView,
    ConfigurationVersionPublishView,
)

urlpatterns = [
    path(
        "configurations/definitions",
        ConfigurationDefinitionListView.as_view(),
        name="configuration-definitions",
    ),
    path(
        "configurations/definitions/<str:definition_code>/versions",
        ConfigurationVersionListView.as_view(),
        name="configuration-definition-versions",
    ),
    path(
        "configurations/versions/<uuid:public_id>/publish",
        ConfigurationVersionPublishView.as_view(),
        name="configuration-version-publish",
    ),
]
