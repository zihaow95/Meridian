"""Configuration API routes."""

from __future__ import annotations

from django.urls import path

from apps.configuration.api.configurations import (
    ConfigurationDefinitionListView,
    ConfigurationDraftCreateView,
    ConfigurationPublicationRequestCreateView,
    ConfigurationPublicationRequestListView,
    ConfigurationPublicationReviewView,
    ConfigurationVersionDetailView,
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
        "configurations/definitions/<str:definition_code>/drafts",
        ConfigurationDraftCreateView.as_view(),
        name="configuration-definition-drafts",
    ),
    path(
        "configurations/publication-requests",
        ConfigurationPublicationRequestListView.as_view(),
        name="configuration-publication-requests",
    ),
    path(
        "configurations/publication-requests/<uuid:public_id>/review",
        ConfigurationPublicationReviewView.as_view(),
        name="configuration-publication-request-review",
    ),
    path(
        "configurations/versions/<uuid:public_id>",
        ConfigurationVersionDetailView.as_view(),
        name="configuration-version-detail",
    ),
    path(
        "configurations/versions/<uuid:public_id>/publication-requests",
        ConfigurationPublicationRequestCreateView.as_view(),
        name="configuration-version-publication-requests",
    ),
    path(
        "configurations/versions/<uuid:public_id>/publish",
        ConfigurationVersionPublishView.as_view(),
        name="configuration-version-publish",
    ),
]
