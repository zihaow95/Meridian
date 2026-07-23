"""Operating data source configuration via locked ConfigurationVersion."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.configuration.models import ConfigurationStatus, ConfigurationVersion
from apps.configuration.schema_registry import OPERATING_SOURCE_MAPPING_CODE, validate_content
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import DataSourceStatus, DataSourceType
from apps.integrations.services.data_sources import (
    ConfigureOperatingDataSource,
    assert_active_for_ingestion,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.dispatcher import dispatch_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.tasks import LocalOutboxPublisher


@pytest.fixture
def ops_department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="OPS",
        name="Operations",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


def _mapping_content(**overrides) -> dict:
    content = {
        "source_priority": 10,
        "mapping_rules": [
            {
                "external_field": "sku_code",
                "internal_field": "sku_code",
            }
        ],
        "reasonable_ranges": {"sales_amount": {"min": "0", "max": "1000000"}},
    }
    content.update(overrides)
    return content


@pytest.mark.django_db(transaction=True)
def test_configure_requires_published_configuration_and_locks_version(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")

    source = ConfigureOperatingDataSource(
        context=CommandContext.for_actor(active_user),
        source_code="ERP_SALES",
        name="ERP sales feed",
        source_type=DataSourceType.API,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()

    assert source.status == DataSourceStatus.ACTIVE
    assert source.configuration_version.status == ConfigurationStatus.PUBLISHED
    assert source.configuration_version.definition.definition_code.startswith(
        OPERATING_SOURCE_MAPPING_CODE
    )
    locked = source.configuration_version.content_json
    assert locked["source_priority"] == 10
    assert locked["mapping_rules"][0]["external_field"] == "sku_code"


@pytest.mark.django_db(transaction=True)
def test_credentials_never_enter_configuration_or_audit(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")

    with pytest.raises(ValidationFailedError):
        ConfigureOperatingDataSource(
            context=CommandContext.for_actor(active_user),
            source_code="ERP_CREDS",
            name="Bad feed",
            source_type=DataSourceType.API,
            owner_department_public_id=ops_department.public_id,
            sensitivity_level="SENSITIVE_CONTROLLED",
            mapping_content=_mapping_content(api_key="secret-token", password="p@ss"),
        ).execute()

    assert not ConfigurationVersion.objects.filter(
        definition__definition_code=OPERATING_SOURCE_MAPPING_CODE,
        content_json__api_key="secret-token",
    ).exists()
    assert not AuditEvent.objects.filter(
        action_code="data_source.configure",
        after_summary__api_key="secret-token",
    ).exists()
    for event in AuditEvent.objects.filter(action_code="data_source.configure"):
        blob = str(event.after_summary) + str(event.before_summary)
        assert "secret-token" not in blob
        assert "p@ss" not in blob


@pytest.mark.django_db(transaction=True)
def test_inactive_source_cannot_build_ingestion_batch(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    source = ConfigureOperatingDataSource(
        context=CommandContext.for_actor(active_user),
        source_code="FILE_FEED",
        name="File feed",
        source_type=DataSourceType.FILE,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="INTERNAL",
        mapping_content=_mapping_content(source_priority=5),
        status=DataSourceStatus.INACTIVE,
    ).execute()

    with pytest.raises(ValidationFailedError):
        assert_active_for_ingestion(source)


@pytest.mark.django_db(transaction=True)
def test_source_priority_and_mapping_come_from_locked_configuration_version(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    source = ConfigureOperatingDataSource(
        context=CommandContext.for_actor(active_user),
        source_code="MANUAL_ENTRY",
        name="Manual",
        source_type=DataSourceType.MANUAL,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="INTERNAL",
        mapping_content=_mapping_content(source_priority=3),
    ).execute()

    version = source.configuration_version
    assert version.content_json["source_priority"] == 3
    assert source.locked_source_priority() == 3
    assert source.locked_mapping_rules() == version.content_json["mapping_rules"]


@pytest.mark.django_db
def test_operating_source_mapping_schema_rejects_script_fields() -> None:
    errors = validate_content(
        OPERATING_SOURCE_MAPPING_CODE,
        _mapping_content(expression="import os"),
    )
    assert errors


@pytest.mark.django_db
def test_configure_data_source_outbox_publishes(active_user, ops_department, grant_action) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    source = ConfigureOperatingDataSource(
        context=CommandContext.for_actor(active_user),
        source_code="API_SRC_OUTBOX",
        name="API",
        source_type=DataSourceType.API,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="INTERNAL",
        mapping_content=_mapping_content(source_priority=1),
    ).execute()
    event = OutboxEvent.objects.filter(
        event_type="data_source.configured", aggregate_id=source.public_id
    ).get()
    assert event.status == OutboxStatus.PENDING
    dispatch_pending_events(publisher=LocalOutboxPublisher(), limit=20)
    event.refresh_from_db()
    assert event.status == OutboxStatus.PUBLISHED
