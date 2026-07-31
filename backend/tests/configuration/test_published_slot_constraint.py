"""MySQL-enforceable uniqueness for the current published configuration version.

A definition may only ever have one PUBLISHED version. Application code alone
cannot guarantee that under concurrency, and MySQL silently drops conditional
unique constraints, so the rule is carried by a nullable slot column that is
occupied only while a version is published.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, migrations

from apps.configuration.models import ConfigurationStatus, ConfigurationVersion
from apps.configuration.services import CreateDraft, PublishVersion

migration_0004 = importlib.import_module(
    "apps.configuration.migrations.0004_current_published_slot"
)


@pytest.mark.django_db
def test_second_published_version_for_one_definition_is_rejected_by_database(
    published_version: ConfigurationVersion,
    file_upload_definition,
    active_user,
) -> None:
    assert published_version.current_published_slot == 1

    with pytest.raises(IntegrityError):
        ConfigurationVersion.objects.create(
            organization=file_upload_definition.organization,
            definition=file_upload_definition,
            version_number=published_version.version_number + 1,
            status=ConfigurationStatus.PUBLISHED,
            content_json={"allowed_mime_types": ["image/png"], "max_bytes": 1_048_576},
            created_by=active_user,
            current_published_slot=1,
        )


@pytest.mark.django_db
def test_publishing_next_version_frees_the_previous_published_slot(
    published_version: ConfigurationVersion,
    file_upload_definition,
    active_user,
) -> None:
    successor = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 2_097_152},
    ).execute()

    PublishVersion(version=successor, actor=active_user).execute()

    published_version.refresh_from_db()
    successor.refresh_from_db()
    assert published_version.status == ConfigurationStatus.RETIRED
    assert published_version.current_published_slot is None
    assert successor.status == ConfigurationStatus.PUBLISHED
    assert successor.current_published_slot == 1


@pytest.mark.django_db
def test_draft_versions_do_not_occupy_the_published_slot(
    draft_version: ConfigurationVersion,
    file_upload_definition,
    active_user,
) -> None:
    sibling = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 1_048_576},
    ).execute()

    assert draft_version.current_published_slot is None
    assert sibling.current_published_slot is None


def _clear_slot(*versions: ConfigurationVersion) -> None:
    """Reproduce an upgraded database, where published rows predate the slot column."""
    ConfigurationVersion.objects.filter(pk__in=[v.pk for v in versions]).update(
        current_published_slot=None
    )


@pytest.mark.django_db
def test_upgrade_backfill_occupies_the_slot_for_versions_already_published(
    published_version: ConfigurationVersion,
    file_upload_definition,
    active_user,
) -> None:
    pending_draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 1_048_576},
    ).execute()
    _clear_slot(published_version)

    migration_0004.occupy_slot_for_published_versions(django_apps, None)

    published_version.refresh_from_db()
    pending_draft.refresh_from_db()
    assert published_version.current_published_slot == 1
    assert pending_draft.current_published_slot is None


@pytest.mark.django_db
def test_upgrade_backfill_stops_instead_of_choosing_between_two_published_versions(
    published_version: ConfigurationVersion,
    file_upload_definition,
    active_user,
) -> None:
    rival = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["image/png"], "max_bytes": 1_048_576},
    ).execute()
    _clear_slot(published_version, rival)
    ConfigurationVersion.objects.filter(pk=rival.pk).update(status=ConfigurationStatus.PUBLISHED)

    with pytest.raises(RuntimeError, match="more than one PUBLISHED"):
        migration_0004.reject_duplicate_published_versions(django_apps, None)


def test_duplicate_guard_runs_before_the_migration_touches_the_schema() -> None:
    """MySQL cannot roll back DDL, so a rejected upgrade must not have altered the table."""
    operations = migration_0004.Migration.operations
    guard_position = next(
        index
        for index, operation in enumerate(operations)
        if getattr(operation, "code", None) is migration_0004.reject_duplicate_published_versions
    )
    first_schema_change = next(
        index
        for index, operation in enumerate(operations)
        if not isinstance(operation, migrations.RunPython)
    )

    assert guard_position < first_schema_change
