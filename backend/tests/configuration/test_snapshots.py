"""Configuration snapshot immutability."""

from __future__ import annotations

import pytest

from apps.configuration.services import CreateSnapshot


@pytest.mark.django_db
def test_snapshot_content_hash_matches_version(published_version, active_user) -> None:
    snapshot = CreateSnapshot(
        version=published_version,
        reference_type="project",
        reference_id=published_version.public_id,
        actor=active_user,
    ).execute()
    assert snapshot.content_hash == published_version.content_digest
