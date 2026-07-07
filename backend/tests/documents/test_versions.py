"""Document version chain."""

from __future__ import annotations

import pytest

from apps.documents.services.uploads import complete_upload


@pytest.mark.django_db
def test_upload_creates_version_one(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    assert version.version_number == 1
    assert version.document.current_version_id == version.id
