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

from apps.configuration.models import ConfigurationVersion
from apps.documents.models import (
    DocumentSource,
    DocumentVersion,
    UploadSession,
)
from apps.documents.policy import resolve_upload_policy
from apps.documents.services.catalog import (
    CatalogItemRules,
    CatalogItemUnavailable,
    read_catalog_item,
    resolve_catalog_item,
)
from apps.documents.services.ingest import (
    StagedContent,
    activate_staged_content,
    stage_controlled_content,
)
from apps.documents.storage.base import FileStorage, StorageMoveFailed
from apps.identity.models.user import User

# Magic numbers for the formats the platform can verify. A declared type in this
# table must be backed by matching bytes; anything else is a lie about content.
_MIME_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
_VERIFIABLE_MIME_TYPES = frozenset(mime for _, mime in _MIME_SIGNATURES)
_SIGNATURE_READ_BYTES = 16


class UploadValidationFailed(Exception):
    pass


def detect_mime_type(head: bytes) -> str | None:
    for signature, mime_type in _MIME_SIGNATURES:
        if head.startswith(signature):
            return mime_type
    return None


@dataclass(frozen=True)
class CreateUploadSession:
    actor: User
    original_filename: str
    declared_mime_type: str
    storage: FileStorage
    ttl_minutes: int = 60
    catalog_item_code: str | None = None

    def execute(self) -> UploadSession:
        rules = (
            resolve_catalog_item(
                organization=self.actor.organization,
                item_code=self.catalog_item_code,
            )
            if self.catalog_item_code is not None
            else None
        )
        allowed = (
            rules.allowed_mime_types
            if rules is not None
            else resolve_upload_policy(self.actor.organization).allowed_mime_types
        )
        if self.declared_mime_type not in allowed:
            raise UploadValidationFailed("MIME type not allowed.")

        temp_name = f"{uuid.uuid4()}.part"
        temp_path = self.storage.temp_dir() / temp_name
        return UploadSession.objects.create(
            organization=self.actor.organization,
            uploaded_by=self.actor,
            temp_path=str(temp_path),
            original_filename=self.original_filename,
            declared_mime_type=self.declared_mime_type,
            catalog_item_code=self.catalog_item_code or "",
            catalog_version_public_id=(
                rules.catalog_version_public_id if rules is not None else None
            ),
            catalog_content_digest=(rules.catalog_content_digest if rules is not None else ""),
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
        staged: StagedContent | None = None
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

            rules = _locked_catalog_rules(session)
            if rules is not None:
                allowed_mime_types = rules.allowed_mime_types
                max_bytes = rules.max_bytes
            else:
                policy = resolve_upload_policy(session.organization)
                allowed_mime_types = policy.allowed_mime_types
                max_bytes = policy.max_bytes

            if session.declared_mime_type not in allowed_mime_types:
                raise UploadValidationFailed("MIME type not allowed.")
            if session.size_bytes <= 0:
                raise UploadValidationFailed("Uploaded file is empty.")
            if session.size_bytes > max_bytes:
                raise UploadValidationFailed("Uploaded file exceeds size limit.")

            if session.document_version_id is not None:
                # The payload passed the catalog signature check when this version
                # was bound, and the bytes may already have been relocated into
                # permanent storage by whoever bound it. Reading the temp file again
                # would fail on the winner's success rather than on a real defect.
                version = DocumentVersion.objects.select_related("file_object").get(
                    id=session.document_version_id
                )
                staged = StagedContent(
                    version_id=version.id,
                    file_object_id=version.file_object_id,
                    temp_path=Path(session.temp_path),
                    object_key=version.file_object.object_key,
                )
            else:
                if rules is not None:
                    _assert_content_matches_declaration(session)
                version, staged = stage_controlled_content(
                    organization=session.organization,
                    source_temp_path=Path(session.temp_path),
                    sha256=session.sha256,
                    size_bytes=session.size_bytes,
                    original_filename=session.original_filename,
                    mime_type=session.declared_mime_type,
                    uploaded_by=session.uploaded_by,
                    source=DocumentSource.PROJECT,
                    document_code=self.document_code,
                    title=self.title,
                    catalog_item_code=session.catalog_item_code,
                    sensitivity_level=(
                        rules.default_sensitivity_level if rules is not None else "INTERNAL"
                    ),
                )
                session.document_version = version
                session.save(update_fields=["document_version"])

        assert staged is not None
        try:
            activated = activate_staged_content(staged, self.storage)
        except StorageMoveFailed:
            # Leave the session incomplete with the same bound PENDING version;
            # the temp file remains for a true retry.
            raise
        with transaction.atomic():
            session = UploadSession.objects.select_for_update().get(
                public_id=self.session_public_id
            )
            if session.completed_at is None:
                session.completed_at = timezone.now()
                session.save(update_fields=["completed_at"])
            elif session.document_version_id != activated.id:
                raise UploadValidationFailed("Upload session already completed.")
        return activated


def _locked_catalog_rules(session: UploadSession) -> CatalogItemRules | None:
    """Read the rules from the catalog version this session started under."""
    if not session.catalog_item_code or session.catalog_version_public_id is None:
        return None

    catalog_version = ConfigurationVersion.objects.filter(
        public_id=session.catalog_version_public_id
    ).first()
    if catalog_version is None:
        raise CatalogItemUnavailable("The catalog version this upload started under is gone.")
    return read_catalog_item(
        catalog_version=catalog_version,
        item_code=session.catalog_item_code,
    )


def _assert_content_matches_declaration(session: UploadSession) -> None:
    with Path(session.temp_path).open("rb") as handle:
        head = handle.read(_SIGNATURE_READ_BYTES)

    detected = detect_mime_type(head)
    if detected == session.declared_mime_type:
        return
    if detected is not None or session.declared_mime_type in _VERIFIABLE_MIME_TYPES:
        raise UploadValidationFailed("File content does not match the declared MIME type.")


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
