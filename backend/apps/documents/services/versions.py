"""Document version chain helpers."""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from apps.documents.models import Document, DocumentVersion, VersionStatus
from apps.identity.models.user import User


@dataclass(frozen=True)
class CreateNextVersion:
    document: Document
    file_object_id: int
    actor: User
    original_filename: str
    declared_mime_type: str

    def execute(self) -> DocumentVersion:
        latest = document_latest_version(self.document)
        next_number = 1 if latest is None else latest.version_number + 1
        now = timezone.now()
        version = DocumentVersion.objects.create(
            organization=self.document.organization,
            document=self.document,
            version_number=next_number,
            file_object_id=self.file_object_id,
            original_filename=self.original_filename,
            declared_mime_type=self.declared_mime_type,
            detected_mime_type=self.declared_mime_type,
            status=VersionStatus.DRAFT,
            uploaded_by=self.actor,
            uploaded_at=now,
            supersedes_version=latest,
        )
        return version


def document_latest_version(document: Document) -> DocumentVersion | None:
    return document.versions.order_by("-version_number").first()
