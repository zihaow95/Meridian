"""Storage reconciliation."""

from __future__ import annotations

import pytest

from apps.documents.models import StorageStatus
from apps.documents.services.reconcile import ReconcileStorage
from apps.documents.services.uploads import complete_upload


@pytest.mark.django_db
def test_reconcile_marks_missing_active_files(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    path = file_storage.final_path_for(version.file_object.object_key)
    path.unlink()
    result = ReconcileStorage(storage=file_storage).execute()
    version.file_object.refresh_from_db()
    assert result["marked_missing"] == 1
    assert version.file_object.storage_status == StorageStatus.MISSING
