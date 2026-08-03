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
def test_retired_configuration_cannot_be_edited(
    published_version, file_upload_definition, active_user
) -> None:
    from apps.configuration.models import ConfigurationStatus
    from apps.configuration.services import CreateDraft, PublishVersion

    next_draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 2_097_152},
    ).execute()
    PublishVersion(version=next_draft, actor=active_user).execute()
    published_version.refresh_from_db()
    assert published_version.status == ConfigurationStatus.RETIRED

    with pytest.raises(PublishedConfigurationImmutable):
        published_version.replace_content({"changed": True})


@pytest.mark.django_db
def test_published_configuration_digest_cannot_be_rewritten(published_version) -> None:
    published_version.content_digest = "0" * 64
    with pytest.raises(PublishedConfigurationImmutable):
        published_version.save(update_fields=["content_digest", "updated_at"])


@pytest.mark.django_db
def test_publish_refuses_actor_without_publish_action(
    file_upload_definition, active_user, another_active_user
) -> None:
    from apps.platform.api.errors import PermissionDeniedError

    draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()
    with pytest.raises(PermissionDeniedError):
        PublishVersion(version=draft, actor=another_active_user).execute()


@pytest.mark.django_db
def test_create_draft_refuses_actor_without_draft_action(
    file_upload_definition, another_active_user
) -> None:
    from apps.platform.api.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        CreateDraft(
            actor=another_active_user,
            definition=file_upload_definition,
            content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
        ).execute()


@pytest.mark.django_db
def test_publish_registers_outbox_event(published_version) -> None:
    from apps.platform.outbox.models import OutboxEvent

    event = OutboxEvent.objects.get(aggregate_id=published_version.public_id)
    assert event.event_type == "configuration.published"


@pytest.mark.django_db
def test_create_draft_writes_audit(file_upload_definition, active_user) -> None:
    from apps.audit.models import AuditEvent

    draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()

    assert AuditEvent.objects.filter(
        action_code="configuration.draft.create",
        resource_public_id=draft.public_id,
        actor_user=active_user,
    ).exists()


@pytest.mark.django_db
def test_validate_failure_persists_failed_status_and_errors(
    file_upload_definition, active_user
) -> None:
    from apps.audit.models import AuditEvent, AuditResult
    from apps.configuration.models import ConfigurationStatus
    from apps.configuration.services import ConfigurationValidationFailed, ValidateVersion

    draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": "not-a-number"},
    ).execute()

    with pytest.raises(ConfigurationValidationFailed):
        ValidateVersion(version=draft, actor=active_user).execute()

    draft.refresh_from_db()
    assert draft.status == ConfigurationStatus.FAILED
    assert draft.validation_errors
    assert AuditEvent.objects.filter(
        action_code="configuration.draft.create",
        resource_public_id=draft.public_id,
        result=AuditResult.FAILURE,
    ).exists()


@pytest.mark.django_db
def test_snapshot_writes_audit(file_upload_definition, active_user) -> None:
    from apps.audit.models import AuditEvent

    v1 = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()
    v1 = PublishVersion(version=v1, actor=active_user).execute()
    CreateSnapshot(
        version=v1,
        reference_type="project",
        reference_id=v1.public_id,
        actor=active_user,
    ).execute()

    assert AuditEvent.objects.filter(
        action_code="configuration.version.read",
        resource_public_id=v1.public_id,
        actor_user=active_user,
    ).exists()


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
