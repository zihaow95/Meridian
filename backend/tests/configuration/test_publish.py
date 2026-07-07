"""Immutable configuration version rules."""

from __future__ import annotations

import pytest

from apps.configuration.models import PublishedConfigurationImmutable
from apps.configuration.services import CreateDraft, CreateSnapshot, PublishVersion


@pytest.mark.django_db
def test_published_configuration_cannot_be_edited(published_version) -> None:
    with pytest.raises(PublishedConfigurationImmutable):
        published_version.replace_content({"changed": True})


@pytest.mark.django_db
def test_publish_registers_outbox_event(published_version) -> None:
    from apps.platform.outbox.models import OutboxEvent

    event = OutboxEvent.objects.get(aggregate_id=published_version.public_id)
    assert event.event_type == "configuration.published"


@pytest.mark.django_db
def test_snapshot_preserves_published_content(file_upload_definition, active_user) -> None:
    v1 = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()
    v1 = PublishVersion(version=v1, actor=active_user).execute()
    snapshot = CreateSnapshot(
        version=v1,
        reference_type="project",
        reference_id=v1.public_id,
        actor=active_user,
    ).execute()

    v2 = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 2_097_152},
    ).execute()
    PublishVersion(version=v2, actor=active_user).execute()

    snapshot.refresh_from_db()
    assert snapshot.content_copy == {
        "allowed_mime_types": ["application/pdf"],
        "max_bytes": 1_048_576,
    }
