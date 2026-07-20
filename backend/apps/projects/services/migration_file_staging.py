"""Stage migration history file payloads onto disk without storing binary in MySQL."""

from __future__ import annotations

import binascii
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.documents.policy import UploadPolicy, resolve_upload_policy
from apps.documents.storage.base import FileStorage
from apps.identity.models.organization import Organization
from apps.projects.errors import MigrationImportFailed

_CONTENT_KEYS = frozenset({"content_base64", "content_text", "content"})


def resolve_migration_staging_path(storage: FileStorage, relpath: str) -> Path:
    """Resolve a server-issued staging path and reject traversal or absolute paths."""

    rel = Path(str(relpath))
    if rel.is_absolute() or ".." in rel.parts or rel.drive:
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


def _base64_byte_chunks(raw: str, *, chunk_chars: int = 65_536) -> Iterator[bytes]:
    """Decode base64 incrementally without building a cleaned mega-string."""

    buffer = ""
    for char in str(raw):
        if char.isspace():
            continue
        buffer += char
        step = chunk_chars - (chunk_chars % 4)
        if step < 4:
            step = 4
        while len(buffer) >= step:
            piece = buffer[:step]
            buffer = buffer[step:]
            try:
                yield binascii.a2b_base64(piece)
            except binascii.Error as exc:
                raise MigrationImportFailed(
                    message="Migrated history file content_base64 is not valid base64."
                ) from exc
    if buffer:
        try:
            yield binascii.a2b_base64(buffer)
        except binascii.Error as exc:
            raise MigrationImportFailed(
                message="Migrated history file content_base64 is not valid base64."
            ) from exc


def stage_history_file_payload(
    item: dict[str, Any],
    *,
    storage: FileStorage,
    organization: Organization,
    allow_existing_staging: bool = False,
) -> dict[str, Any]:
    """Persist file bytes under the storage temp dir; return MySQL-safe metadata."""

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    mime = str(item.get("mime_type") or "application/octet-stream")
    policy = resolve_upload_policy(organization)

    if item.get("staging_relpath"):
        if not allow_existing_staging:
            raise MigrationImportFailed(
                message="Client-supplied staging_relpath is not allowed on import."
            )
        existing = resolve_migration_staging_path(storage, str(item["staging_relpath"]))
        if not existing.is_file():
            raise MigrationImportFailed(
                message=f"Staged migration file missing: {item['staging_relpath']}"
            )
        return {
            key: value
            for key, value in {
                "filename": filename,
                "deliverable_code": item.get("deliverable_code"),
                "source_note": item.get("source_note"),
                "source_version": item.get("source_version")
                or item.get("migration_source_version"),
                "mime_type": mime,
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
                "staging_relpath": str(item["staging_relpath"]),
                "pending_version_public_id": item.get("pending_version_public_id"),
            }.items()
            if value is not None
        }

    staging_name = f"migration/{uuid4().hex}.part"
    temp_path = storage.temp_dir() / staging_name

    if item.get("content_base64") is not None:
        sha256, size_bytes = _write_streaming_sha(
            temp_path,
            _base64_byte_chunks(str(item["content_base64"])),
            policy=policy,
            mime_type=mime,
        )
    elif item.get("content_text") is not None:
        encoded = str(item["content_text"]).encode("utf-8")

        def _once() -> Iterator[bytes]:
            yield encoded

        sha256, size_bytes = _write_streaming_sha(temp_path, _once(), policy=policy, mime_type=mime)
    elif isinstance(item.get("content"), bytes | bytearray):
        payload = bytes(item["content"])

        def _bytes_once() -> Iterator[bytes]:
            yield payload

        sha256, size_bytes = _write_streaming_sha(
            temp_path, _bytes_once(), policy=policy, mime_type=mime
        )
    else:
        raise MigrationImportFailed(
            message=(
                "Migrated history file requires real content "
                "(content_base64/content_text) to write a storage object."
            )
        )

    if size_bytes <= 0:
        temp_path.unlink(missing_ok=True)
        raise MigrationImportFailed(message="Migrated history file content is empty.")

    metadata: dict[str, Any] = {
        "filename": filename,
        "mime_type": mime,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "staging_relpath": staging_name,
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
    allow_existing_staging: bool = False,
) -> list[dict[str, Any]]:
    """Stage every history file entry; never return binary/content fields."""

    staged: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise MigrationImportFailed(
                message="Migrated history file entries must be objects with content."
            )
        if any(key in item for key in _CONTENT_KEYS) or (
            allow_existing_staging and item.get("staging_relpath")
        ):
            staged.append(
                stage_history_file_payload(
                    item,
                    storage=storage,
                    organization=organization,
                    allow_existing_staging=allow_existing_staging,
                )
            )
            continue
        staged.append(
            {
                key: value
                for key, value in {
                    "filename": str(item.get("filename") or item.get("name") or "migrated-file"),
                    "deliverable_code": item.get("deliverable_code"),
                    "source_note": item.get("source_note"),
                    "source_version": item.get("source_version")
                    or item.get("migration_source_version"),
                    "mime_type": item.get("mime_type"),
                    "pending_version_public_id": item.get("pending_version_public_id"),
                }.items()
                if value is not None
            }
        )
    return staged
