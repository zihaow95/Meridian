"""Local filesystem storage adapter (dev/CI and NFS production)."""

from __future__ import annotations

import os
from pathlib import Path

from apps.documents.storage.base import StorageMoveFailed


class FilesystemStorage:
    def __init__(self, root: Path, *, internal_prefix: str = "/protected-files/") -> None:
        self._root = root
        self._internal_prefix = internal_prefix
        self._root.mkdir(parents=True, exist_ok=True)
        self.temp_dir().mkdir(parents=True, exist_ok=True)

    def temp_dir(self) -> Path:
        return self._root / "tmp"

    def final_path_for(self, object_key: str) -> Path:
        return self._root / "objects" / object_key

    def atomic_move(self, source: Path, object_key: str) -> None:
        destination = self.final_path_for(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(source, destination)
        except OSError as exc:
            raise StorageMoveFailed(str(exc)) from exc

    def internal_redirect_header(self, object_key: str) -> str:
        return f"{self._internal_prefix}{object_key}"
