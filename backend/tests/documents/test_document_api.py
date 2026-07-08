"""Document upload and download API rules."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.documents.models import VersionStatus


@pytest.mark.django_db
def test_upload_requires_permission(client: Client, active_user) -> None:
    client.force_login(active_user)
    response = client.post(
        "/api/v1/documents/uploads",
        data={
            "file": io.BytesIO(b"%PDF-1.4 sample"),
            "original_filename": "report.pdf",
            "declared_mime_type": "application/pdf",
        },
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_upload_and_complete_document(client: Client, active_user, grant_action, settings) -> None:
    scratch_root = Path(__file__).resolve().parents[2] / "var" / "pytest-scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as tmp:
        settings.FILE_STORAGE_ROOT = Path(tmp)
        grant_action(active_user, "document.version.upload", "document.version")
        client.force_login(active_user)

        upload_response = client.post(
            "/api/v1/documents/uploads",
            data={
                "file": SimpleUploadedFile(
                    "report.pdf",
                    b"%PDF-1.4 sample",
                    content_type="application/pdf",
                ),
                "original_filename": "report.pdf",
                "declared_mime_type": "application/pdf",
            },
        )
        assert upload_response.status_code == 201
        session_public_id = upload_response.json()["public_id"]

        complete_response = client.post(
            f"/api/v1/documents/uploads/{session_public_id}/complete",
            data={},
            content_type="application/json",
        )
        assert complete_response.status_code == 200
        document_public_id = complete_response.json()["document_public_id"]

        grant_action(active_user, "document.version.download", "document.version")
        versions_response = client.get(f"/api/v1/documents/{document_public_id}/versions")
        assert versions_response.status_code == 200
        assert len(versions_response.json()) == 1
        assert versions_response.json()[0]["status"] == VersionStatus.CONTROLLED
