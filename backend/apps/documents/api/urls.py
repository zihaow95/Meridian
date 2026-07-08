"""Document API routes."""

from __future__ import annotations

from django.urls import path

from apps.documents.api.documents import (
    DocumentDownloadView,
    DocumentVersionDownloadTicketView,
    DocumentVersionListView,
)
from apps.documents.api.uploads import UploadSessionCompleteView, UploadSessionCreateView

urlpatterns = [
    path("documents/uploads", UploadSessionCreateView.as_view(), name="document-uploads"),
    path(
        "documents/uploads/<uuid:public_id>/complete",
        UploadSessionCompleteView.as_view(),
        name="document-upload-complete",
    ),
    path(
        "documents/<uuid:document_public_id>/versions",
        DocumentVersionListView.as_view(),
        name="document-versions",
    ),
    path(
        "documents/versions/<uuid:version_public_id>/download-ticket",
        DocumentVersionDownloadTicketView.as_view(),
        name="document-version-download-ticket",
    ),
    path(
        "documents/download/<str:token>",
        DocumentDownloadView.as_view(),
        name="document-download",
    ),
]
