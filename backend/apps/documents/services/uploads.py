"""Upload session lifecycle."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    UploadSession,
    VersionStatus,
)
from apps.documents.policy import resolve_upload_policy
from apps.documents.storage.base import FileStorage, StorageMoveFailed
from apps.identity.models.user import User


class UploadValidationFailed(Exception):
    pass


@dataclass(frozen=True)
class CreateUploadSession:
    actor: User
    original_filename: str
    declared_mime_type: str
    storage: FileStorage
    ttl_minutes: int = 60

    def execute(self) -> UploadSession:
        policy = resolve_upload_policy(self.actor.organization)
        if self.declared_mime_type not in policy.allowed_mime_types:
            raise UploadValidationFailed("MIME type not allowed.")

        temp_name = f"{uuid.uuid4()}.part"
        temp_path = self.storage.temp_dir() / temp_name
        return UploadSession.objects.create(
            organization=self.actor.organization,
            uploaded_by=self.actor,
            temp_path=str(temp_path),
            original_filename=self.original_filename,
            declared_mime_type=self.declared_mime_type,
            expires_at=timezone.now() + timedelta(minutes=self.ttl_minutes),
        )


@dataclass(frozen=True)
class CompleteUpload:
    session_public_id: uuid.UUID
    actor: User
    storage: FileStorage
    document_code: str | None = None
    title: str | None = None

    def execute(self) -> DocumentVersion:
        with transaction.atomic():
            session = UploadSession.objects.select_for_update().get(
                public_id=self.session_public_id
            )
            if session.completed_at is not None:
                raise UploadValidationFailed("Upload session already completed.")
            if session.expires_at <= timezone.now():
                raise UploadValidationFailed("Upload session expired.")
            if session.uploaded_by_id != self.actor.id:
                raise UploadValidationFailed("Upload session belongs to another user.")

            policy = resolve_upload_policy(session.organization)
            if session.declared_mime_type not in policy.allowed_mime_types:
                raise UploadValidationFailed("MIME type not allowed.")
            if session.size_bytes <= 0:
                raise UploadValidationFailed("Uploaded file is empty.")
            if session.size_bytes > policy.max_bytes:
                raise UploadValidationFailed("Uploaded file exceeds size limit.")

            object_key = f"{uuid.uuid4()}/{uuid.uuid4()}"
            now = timezone.now()
            document_code = self.document_code or f"DOC-{uuid.uuid4().hex[:12].upper()}"
            title = self.title or session.original_filename

            file_object = FileObject.objects.create(
                organization=session.organization,
                storage_backend=StorageBackend.NAS_NFS,
                object_key=object_key,
                size_bytes=session.size_bytes,
                sha256=session.sha256,
                detected_mime_type=session.declared_mime_type,
                storage_status=StorageStatus.PENDING,
            )
            document = Document.objects.create(
                organization=session.organization,
                document_code=document_code,
                title=title,
                source=DocumentSource.PROJECT,
            )
            version = DocumentVersion.objects.create(
                organization=session.organization,
                document=document,
                version_number=1,
                file_object=file_object,
                original_filename=session.original_filename,
                declared_mime_type=session.declared_mime_type,
                detected_mime_type=session.declared_mime_type,
                status=VersionStatus.DRAFT,
                uploaded_by=session.uploaded_by,
                uploaded_at=now,
            )
            try:
                self.storage.atomic_move(Path(session.temp_path), object_key)
            except StorageMoveFailed:
                raise
            file_object.storage_status = StorageStatus.ACTIVE
            file_object.save(update_fields=["storage_status"])
            version.status = VersionStatus.CONTROLLED
            version.controlled_at = now
            version.save(update_fields=["status", "controlled_at"])
            document.current_version = version
            document.save(update_fields=["current_version"])
            session.completed_at = now
            session.save(update_fields=["completed_at"])

        return version


def complete_upload(
    session_public_id: uuid.UUID,
    *,
    actor: User,
    storage: FileStorage,
    document_code: str | None = None,
    title: str | None = None,
) -> DocumentVersion:
    return CompleteUpload(
        session_public_id=session_public_id,
        actor=actor,
        storage=storage,
        document_code=document_code,
        title=title,
    ).execute()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_download_token() -> str:
    return secrets.token_urlsafe(32)
