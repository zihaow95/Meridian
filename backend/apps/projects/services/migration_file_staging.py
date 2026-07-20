"""Stage migration history file payloads onto disk without storing binary in MySQL."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.documents.storage.base import FileStorage
from apps.projects.errors import MigrationImportFailed

_CONTENT_KEYS = frozenset({"content_base64", "content_text", "content"})


def _write_streaming_sha(path: Path, chunks: Any) -> tuple[str, int]:
    """Write iterable of bytes chunks to ``path`` and return (sha256, size)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as handle:
        for chunk in chunks:
            if not chunk:
                continue
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _base64_chunks(raw: str, *, chunk_chars: int = 65_536) -> Any:
    """Yield decoded base64 chunks without retaining the full decoded payload.

    The source string may already be in memory (JSON body), but decoded bytes
    are written in pieces so confirm/materialize never reloads a second full
    copy from MySQL.
    """

    cleaned = "".join(str(raw).split())
    if not cleaned:
        return
    # Process in multiples of 4 so each slice is independently decodable.
    step = chunk_chars - (chunk_chars % 4)
    if step < 4:
        step = 4
    for index in range(0, len(cleaned), step):
        piece = cleaned[index : index + step]
        try:
            yield base64.b64decode(piece, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MigrationImportFailed(
                message="Migrated history file content_base64 is not valid base64."
            ) from exc


def stage_history_file_payload(item: dict[str, Any], *, storage: FileStorage) -> dict[str, Any]:
    """Persist file bytes under the storage temp dir; return MySQL-safe metadata."""

    filename = str(item.get("filename") or item.get("name") or "migrated-file")
    mime = str(item.get("mime_type") or "application/octet-stream")
    staging_name = f"migration/{uuid4().hex}.part"
    temp_path = storage.temp_dir() / staging_name

    if item.get("content_base64") is not None:
        sha256, size_bytes = _write_streaming_sha(
            temp_path, _base64_chunks(str(item["content_base64"]))
        )
    elif item.get("content_text") is not None:
        encoded = str(item["content_text"]).encode("utf-8")

        def _once() -> Any:
            yield encoded

        sha256, size_bytes = _write_streaming_sha(temp_path, _once())
    elif isinstance(item.get("content"), bytes | bytearray):
        payload = bytes(item["content"])

        def _bytes_once() -> Any:
            yield payload

        sha256, size_bytes = _write_streaming_sha(temp_path, _bytes_once())
    elif item.get("staging_relpath"):
        # Already staged (idempotent re-import of metadata-only rows).
        existing = storage.temp_dir() / str(item["staging_relpath"])
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
            }.items()
            if value is not None
        }
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


def stage_history_file_list(items: list[Any], *, storage: FileStorage) -> list[dict[str, Any]]:
    """Stage every history file entry; never return binary/content fields."""

    staged: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise MigrationImportFailed(
                message="Migrated history file entries must be objects with content."
            )
        if any(key in item for key in _CONTENT_KEYS) or item.get("staging_relpath"):
            staged.append(stage_history_file_payload(item, storage=storage))
            continue
        # Metadata without bytes: keep only audit fields; confirm fails closed later.
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
                }.items()
                if value is not None
            }
        )
    return staged
