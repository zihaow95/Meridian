"""Resolve the configured file storage backend."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from apps.documents.storage.filesystem import FilesystemStorage


def get_file_storage() -> FilesystemStorage:
    root = Path(getattr(settings, "FILE_STORAGE_ROOT", settings.BASE_DIR / "var" / "files"))
    return FilesystemStorage(root)
