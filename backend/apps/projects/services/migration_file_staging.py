"""Stage migration history file payloads onto disk without storing binary in MySQL."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.documents.policy import UploadPolicy, resolve_upload_policy
from apps.documents.storage.base import FileStorage
from apps.identity.models.organization import Organization
from apps.projects.errors import MigrationImportFailed

_CLIENT_FORBIDDEN_KEYS = frozenset(
    {
        "content_base64",
        "content_text",
        "content",
        "pending_version_public_id",
    }
)


def resolve_migration_staging_path(storage: FileStorage, relpath: str) -> Path:
    """Resolve a server-issued staging path and reject traversal or absolute paths."""

    rel = Path(str(relpath))
    if rel.is_absolute() or ".." in rel.parts or rel.drive:
        raise MigrationImportFailed(message="Invalid migration staging path.")
    if not str(relpath).replace("\\", "/").startswith("migration/"):
        raise MigrationImportFailed(message="Invalid migration staging path.")
    root = storage.temp_dir().resolve()
    candidate = (storage.temp_dir() / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MigrationImportFailed(message="Invalid migration staging path.") from exc
    return candidate


def _write_streaming_sha(
    path: Path,
    chunks: Iterator[bytes],
    *,
    policy: UploadPolicy,
    mime_type: str,
) -> tuple[str, int]:
    """Write byte chunks to ``path``; enforce upload policy; return (sha256, size)."""

    if mime_type not in policy.allowed_mime_types:
        raise MigrationImportFailed(message="MIME type not allowed for migrated history file.")

    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as handle:
        for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > policy.max_bytes:
                raise MigrationImportFailed(message="Migrated history file exceeds size limit.")
            handle.write(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def stream_stage_migration_file(
    *,
    chunks: Iterator[bytes],
    filename: str,
    mime_type: str,
    storage: FileStorage,
    organization: Organization,
) -> dict[str, Any]:
    """Stream file bytes into ``tmp/migration/*.part`` (true streaming entry)."""

    policy = resolve_upload_policy(organization)
    staging_name = f"migration/{uuid4().hex}.part"
    temp_path = storage.temp_dir() / staging_name
    try:
        sha256, size_bytes = _write_streaming_sha(
            temp_path,
            chunks,
            policy=policy,
            mime_type=mime_type,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    if size_bytes <= 0:
        temp_path.unlink(missing_ok=True)
        raise MigrationImportFailed(message="Migrated history file content is empty.")
    return {
        "filename": filename,
        "mime_type": mime_type,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "staging_relpath": staging_name,
    }


def _verify_existing_staging(
    item: dict[str, Any],
    *,
    storage: FileStorage,
    organization: Organization,
) -> dict[str, Any]:
    """Accept only a server-issued staging path that still exists on disk."""

    for key in _CLIENT_FORBIDDEN_KEYS:
        if key in item:
            raise MigrationImportFailed(
                message=f"Client-supplied {key} is not allowed on migration import."
            )
    staging_relpath = item.get("staging_relpath")
    if not staging_relpath:
        raise MigrationImportFailed(
            message=(
                "Migrated history file requires a prior streaming stage "
                "(staging_relpath); inline Base64/content is not accepted."
            )
        )
    path = resolve_migration_staging_path(storage, str(staging_relpath))
    if not path.is_file():
        raise MigrationImportFailed(message=f"Staged migration file missing: {staging_relpath}")

    policy = resolve_upload_policy(organization)
    mime = str(item.get("mime_type") or "application/octet-stream")
    if mime not in policy.allowed_mime_types:
        raise MigrationImportFailed(message="MIME type not allowed for migrated history file.")

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > policy.max_bytes:
                raise MigrationImportFailed(message="Migrated history file exceeds size limit.")
            digest.update(chunk)
    sha256 = digest.hexdigest()
    declared_sha = item.get("sha256")
    declared_size = item.get("size_bytes")
    if declared_sha and str(declared_sha) != sha256:
        raise MigrationImportFailed(message="Staged migration file sha256 mismatch.")
    if declared_size is not None and int(declared_size) != size:
        raise MigrationImportFailed(message="Staged migration file size_bytes mismatch.")

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    metadata: dict[str, Any] = {
        "filename": filename,
        "mime_type": mime,
        "sha256": sha256,
        "size_bytes": size,
        "staging_relpath": str(staging_relpath).replace("\\", "/"),
    }
    for key in ("deliverable_code", "source_note", "source_version", "migration_source_version"):
        if item.get(key) is not None:
            metadata[key if key != "migration_source_version" else "source_version"] = item.get(key)
    return metadata


def stage_history_file_list(
    items: list[Any],
    *,
    storage: FileStorage,
    organization: Organization,
) -> list[dict[str, Any]]:
    """Normalize history file entries for MySQL; never accept inline binary or version ids."""

    staged: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise MigrationImportFailed(
                message="Migrated history file entries must be objects with content."
            )
        staged.append(_verify_existing_staging(item, storage=storage, organization=organization))
    return staged
