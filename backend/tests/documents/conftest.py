"""Document test fixtures."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

import pytest

from apps.documents.models import UploadSession
from apps.documents.services.uploads import CreateUploadSession
from apps.documents.storage.base import StorageMoveFailed
from apps.documents.storage.filesystem import FilesystemStorage
from apps.identity.models.user import User

_TEST_STORAGE_ROOT = Path(__file__).resolve().parent / "_storage"


class FailingMoveStorage(FilesystemStorage):
    def atomic_move(self, source: Path, object_key: str) -> None:
        raise StorageMoveFailed("simulated move failure")


@pytest.fixture
def file_storage() -> FilesystemStorage:
    root = _TEST_STORAGE_ROOT / uuid.uuid4().hex
    storage = FilesystemStorage(root)
    yield storage
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def storage_that_fails_move() -> FailingMoveStorage:
    root = _TEST_STORAGE_ROOT / f"failing-{uuid.uuid4().hex}"
    storage = FailingMoveStorage(root)
    yield storage
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def upload_session(active_user: User, file_storage: FilesystemStorage) -> UploadSession:
    session = CreateUploadSession(
        actor=active_user,
        original_filename="report.pdf",
        declared_mime_type="application/pdf",
        storage=file_storage,
    ).execute()
    content = b"%PDF-1.4 sample"
    path = Path(session.temp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    session.size_bytes = len(content)
    session.sha256 = hashlib.sha256(content).hexdigest()
    session.save(update_fields=["size_bytes", "sha256"])
    return session
