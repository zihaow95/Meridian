"""Storage adapter protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StorageMoveFailed(Exception):
    pass


class FileStorage(Protocol):
    def temp_dir(self) -> Path: ...

    def final_path_for(self, object_key: str) -> Path: ...

    def atomic_move(self, source: Path, object_key: str) -> None: ...

    def internal_redirect_header(self, object_key: str) -> str: ...
