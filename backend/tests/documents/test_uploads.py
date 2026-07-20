"""Upload atomicity and validation."""

from __future__ import annotations

import pytest

from apps.documents.models import DocumentVersion, FileObject, StorageStatus, VersionStatus
from apps.documents.services.uploads import UploadValidationFailed, complete_upload
from apps.documents.storage.base import StorageMoveFailed


@pytest.mark.django_db
def test_atomic_move_failure_never_activates_file(
    upload_session, storage_that_fails_move, active_user
) -> None:
    with pytest.raises(StorageMoveFailed):
        complete_upload(
            upload_session.public_id,
            actor=active_user,
            storage=storage_that_fails_move,
        )
    assert not FileObject.objects.filter(storage_status=StorageStatus.ACTIVE).exists()
    assert not DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).exists()
    upload_session.refresh_from_db()
    assert upload_session.completed_at is None


@pytest.mark.django_db(transaction=True)
def test_upload_activation_failure_remains_retryable(
    upload_session, storage_that_fails_move, file_storage, active_user
) -> None:
    """A failed move must leave the session incomplete so the client can retry."""

    with pytest.raises(StorageMoveFailed):
        complete_upload(
            upload_session.public_id,
            actor=active_user,
            storage=storage_that_fails_move,
        )
    upload_session.refresh_from_db()
    assert upload_session.completed_at is None

    # Recreate the temp payload for the retry (move deleted the failed temp file).
    from pathlib import Path

    Path(upload_session.temp_path).write_bytes(b"%PDF-1.4 retry body")
    upload_session.sha256 = "a" * 64
    upload_session.size_bytes = 18
    upload_session.save(update_fields=["sha256", "size_bytes"])

    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    assert version.status == VersionStatus.CONTROLLED
    upload_session.refresh_from_db()
    assert upload_session.completed_at is not None


@pytest.mark.django_db
def test_successful_upload_activates_file(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    version.file_object.refresh_from_db()
    assert version.file_object.storage_status == StorageStatus.ACTIVE
    assert version.status == VersionStatus.CONTROLLED


@pytest.mark.django_db(transaction=True)
def test_completed_upload_session_cannot_be_completed_twice(
    upload_session, file_storage, active_user
) -> None:
    complete_upload(upload_session.public_id, actor=active_user, storage=file_storage)

    with pytest.raises(UploadValidationFailed):
        complete_upload(upload_session.public_id, actor=active_user, storage=file_storage)

    assert DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).count() == 1
