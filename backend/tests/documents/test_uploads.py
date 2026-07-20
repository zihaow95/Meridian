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
    """A failed move must keep the temp file and bound PENDING version for retry."""

    from pathlib import Path

    with pytest.raises(StorageMoveFailed):
        complete_upload(
            upload_session.public_id,
            actor=active_user,
            storage=storage_that_fails_move,
        )
    upload_session.refresh_from_db()
    assert upload_session.completed_at is None
    assert upload_session.document_version_id is not None
    assert Path(upload_session.temp_path).is_file()
    bound_version_id = upload_session.document_version_id

    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    assert version.status == VersionStatus.CONTROLLED
    assert version.id == bound_version_id
    upload_session.refresh_from_db()
    assert upload_session.completed_at is not None
    assert DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).count() == 1


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


@pytest.mark.django_db(transaction=True)
def test_concurrent_complete_upload_leaves_one_controlled_version(
    upload_session, file_storage, active_user
) -> None:
    """Two concurrent completes settle to one ACTIVE/CONTROLLED MySQL fact."""

    import threading

    from django.db import connection

    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _complete(label: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            complete_upload(
                upload_session.public_id,
                actor=active_user,
                storage=file_storage,
            )
            with lock:
                results.append(f"ok:{label}")
        except UploadValidationFailed:
            with lock:
                results.append(f"done:{label}")
        except Exception as exc:  # noqa: BLE001 - collect for assert
            with lock:
                results.append(f"error:{type(exc).__name__}:{label}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_complete, args=("a",)),
        threading.Thread(target=_complete, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "concurrent complete_upload worker did not finish"

    assert len(results) == 2
    assert not any(item.startswith("error:") for item in results)
    assert any(item.startswith("ok:") for item in results)
    assert DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).count() == 1
    upload_session.refresh_from_db()
    assert upload_session.completed_at is not None
