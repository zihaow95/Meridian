"""Upload atomicity and validation."""

from __future__ import annotations

import pytest

from apps.documents.models import DocumentVersion, FileObject, StorageStatus, VersionStatus
from apps.documents.services.uploads import complete_upload
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
