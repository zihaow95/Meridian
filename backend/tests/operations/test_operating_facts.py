"""Confirm ingestion batches into governed OperatingFact versions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent, AuditResult
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import (
    DataSourceType,
    IngestionBatchStatus,
    IngestionRowStatus,
)
from apps.integrations.services.data_sources import ConfigureOperatingDataSource
from apps.integrations.services.ingestion import (
    CreateIngestionBatch,
    ValidateIngestionBatch,
)
from apps.operations.errors import UnconfirmedIngestionWarnings
from apps.operations.models import (
    CalculationType,
    MetricDefinitionStatus,
    OperatingFact,
    OperatingFactStatus,
)
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.application.command import CommandContext
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import (
    SKU,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)


@pytest.fixture
def ops_department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="OPS-FACT",
        name="Ops Facts",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def sku_channel(organization: Organization, active_user: User) -> tuple[SKU, ChannelConfiguration]:
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-FACT",
        name="Fact yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-READY",
        name="Cup",
        specification="120g",
        status=SKUStatus.ACTIVE,
    )
    channel = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    return sku, channel


def _mapping_content(**overrides) -> dict:
    content = {
        "source_priority": 10,
        "mapping_rules": [
            {"external_field": "sku_code", "internal_field": "sku_code"},
            {"external_field": "channel_code", "internal_field": "channel_code"},
            {"external_field": "sales_amount", "internal_field": "numeric_value"},
            {"external_field": "metric_code", "internal_field": "metric_code"},
            {"external_field": "period_start", "internal_field": "period_start"},
            {"external_field": "period_end", "internal_field": "period_end"},
            {"external_field": "period_granularity", "internal_field": "period_granularity"},
            {"external_field": "unit", "internal_field": "unit"},
            {"external_field": "currency", "internal_field": "currency"},
            {"external_field": "external_record_key", "internal_field": "external_record_key"},
            {"external_field": "source_timestamp", "internal_field": "source_timestamp"},
        ],
        "reasonable_ranges": {"sales_amount": {"min": "0", "max": "1000000"}},
    }
    content.update(overrides)
    return content


def _configure_source(*, user, department, grant_action, source_code, source_type, priority=10):
    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    return ConfigureOperatingDataSource(
        context=CommandContext.for_actor(user),
        source_code=source_code,
        name=source_code,
        source_type=source_type,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(source_priority=priority),
    ).execute()


def _publish_metric(user: User, grant_action) -> None:
    grant_action(user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(user)
    draft = CreateMetricDefinitionDraft(
        context=ctx,
        metric_code="GROSS_SALES",
        name="Gross sales",
        value_type="DECIMAL",
        unit="CNY",
        currency="CNY",
        source_field_codes=["sales_amount"],
        calculation_type=CalculationType.SUM,
        aggregation_rule={"by": ["SKU", "CHANNEL"]},
        window_definition={"granularity": "MONTH"},
        coverage_requirement={"minimum_rate": "0.8"},
        valid_from=timezone.now(),
    ).execute()
    published = PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()
    assert published.status == MetricDefinitionStatus.PUBLISHED


def _row(**overrides) -> dict:
    base = {
        "external_record_key": "ERP-001",
        "sku_code": "SKU-READY",
        "channel_code": "TMALL",
        "metric_code": "GROSS_SALES",
        "period_granularity": "MONTH",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "sales_amount": "1250.50",
        "unit": "CNY",
        "currency": "CNY",
        "source_timestamp": "2026-02-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _ready_batch(*, user, department, grant_action, sku_channel, rows, batch_key="FACT-1"):
    del sku_channel
    _publish_metric(user, grant_action)
    grant_action(user, "ingestion_batch.create", "ingestion_batch")
    grant_action(user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(user)
    source = _configure_source(
        user=user,
        department=department,
        grant_action=grant_action,
        source_code="API_FACTS",
        source_type=DataSourceType.API,
    )
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key=batch_key,
        source_type=DataSourceType.API,
        rows=rows,
    ).execute()
    return ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()


@pytest.mark.django_db(transaction=True)
def test_confirm_imports_valid_rows_and_records_audit_outbox(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    batch = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[_row()],
    )
    result = ConfirmOperatingIngestionBatch(
        context=CommandContext.for_actor(active_user),
        batch_public_id=batch.public_id,
        idempotency_key="confirm-valid-1",
    ).execute()

    batch.refresh_from_db()
    assert batch.status == IngestionBatchStatus.SUCCESS
    assert result.added_count == 1
    assert result.revision_count == 0
    assert result.skipped_count == 0
    assert result.error_count == 0
    fact = OperatingFact.objects.get()
    assert fact.fact_status == OperatingFactStatus.VALID
    assert fact.active_slot == 1
    assert fact.numeric_value == Decimal("1250.50")
    assert fact.period_start == date(2026, 1, 1)
    assert fact.source_record_key == "ERP-001"
    assert batch.rows.get().status == IngestionRowStatus.IMPORTED
    assert (
        AuditEvent.objects.filter(
            action_code="ingestion_batch.confirm",
            result=AuditResult.SUCCESS,
            resource_public_id=batch.public_id,
        ).count()
        == 1
    )
    assert OutboxEvent.objects.filter(event_type="operating_fact.imported").count() == 1


@pytest.mark.django_db(transaction=True)
def test_warning_rows_require_confirm_warnings_or_authorized_confirm(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    batch = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[_row(external_record_key="RANGE-1", sales_amount="9999999")],
        batch_key="WARN-1",
    )
    assert batch.rows.get().status == IngestionRowStatus.WARNING

    with pytest.raises(UnconfirmedIngestionWarnings):
        ConfirmOperatingIngestionBatch(
            context=CommandContext.for_actor(active_user),
            batch_public_id=batch.public_id,
            idempotency_key="warn-no",
        ).execute()
    assert OperatingFact.objects.count() == 0

    result = ConfirmOperatingIngestionBatch(
        context=CommandContext.for_actor(active_user),
        batch_public_id=batch.public_id,
        idempotency_key="warn-yes",
        confirm_warnings=True,
    ).execute()
    assert result.added_count == 1
    assert result.warning_count >= 1
    assert OperatingFact.objects.count() == 1
    row = batch.rows.get()
    row.refresh_from_db()
    assert row.status == IngestionRowStatus.IMPORTED


@pytest.mark.django_db(transaction=True)
def test_late_revision_supersedes_previous_valid_fact(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    first = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[_row(sales_amount="100.00", source_timestamp="2026-02-01T10:00:00+00:00")],
        batch_key="REV-1",
    )
    ConfirmOperatingIngestionBatch(
        context=CommandContext.for_actor(active_user),
        batch_public_id=first.public_id,
        idempotency_key="rev-first",
    ).execute()
    old = OperatingFact.objects.get()
    assert old.fact_status == OperatingFactStatus.VALID
    assert old.active_slot == 1

    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    grant_action(active_user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)
    source = first.source
    second = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="REV-2",
        source_type=DataSourceType.API,
        rows=[
            _row(
                sales_amount="250.00",
                source_timestamp="2026-02-05T12:00:00+00:00",
            )
        ],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=second.public_id).execute()
    result = ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=second.public_id,
        idempotency_key="rev-second",
    ).execute()

    old.refresh_from_db()
    new = OperatingFact.objects.exclude(pk=old.pk).get()
    assert result.revision_count == 1
    assert result.added_count == 0
    assert old.fact_status == OperatingFactStatus.SUPERSEDED
    assert old.active_slot is None
    assert new.fact_status == OperatingFactStatus.VALID
    assert new.active_slot == 1
    assert new.numeric_value == Decimal("250.00")
    assert (
        OperatingFact.objects.filter(
            source=source,
            source_record_key="ERP-001",
            active_slot=1,
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_confirm_idempotency_key_returns_same_result_without_duplicate_facts(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    batch = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[_row()],
        batch_key="IDEM-FACT",
    )
    ctx = CommandContext.for_actor(active_user)
    first = ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key="same-key",
    ).execute()
    second = ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key="same-key",
    ).execute()
    assert first.public_id == second.public_id
    assert OperatingFact.objects.count() == 1
    assert (
        AuditEvent.objects.filter(
            action_code="ingestion_batch.confirm",
            result=AuditResult.SUCCESS,
        ).count()
        == 1
    )
    assert OutboxEvent.objects.filter(event_type="operating_fact.imported").count() == 1


@pytest.mark.django_db(transaction=True)
def test_error_and_unmapped_rows_are_skipped_partial_success_keeps_valid(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    batch = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[
            _row(external_record_key="OK-1"),
            _row(external_record_key="BAD-SKU", sku_code="MISSING"),
            _row(external_record_key="BAD-UNIT", unit="", currency=""),
        ],
        batch_key="PARTIAL-1",
    )
    result = ConfirmOperatingIngestionBatch(
        context=CommandContext.for_actor(active_user),
        batch_public_id=batch.public_id,
        idempotency_key="partial-1",
    ).execute()
    batch.refresh_from_db()
    assert result.added_count == 1
    assert result.error_count >= 1
    assert result.skipped_count >= 1
    assert batch.status == IngestionBatchStatus.PARTIAL_SUCCESS
    assert OperatingFact.objects.count() == 1
    statuses = set(batch.rows.values_list("status", flat=True))
    assert IngestionRowStatus.IMPORTED in statuses
    assert IngestionRowStatus.ERROR in statuses or IngestionRowStatus.UNMAPPED in statuses


@pytest.mark.django_db(transaction=True)
def test_failed_retry_does_not_overwrite_previous_valid_facts(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    from apps.integrations.services.ingestion import RetryIngestionBatch

    first = _ready_batch(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        sku_channel=sku_channel,
        rows=[_row()],
        batch_key="KEEP-1",
    )
    ConfirmOperatingIngestionBatch(
        context=CommandContext.for_actor(active_user),
        batch_public_id=first.public_id,
        idempotency_key="keep-first",
    ).execute()
    assert OperatingFact.objects.filter(fact_status=OperatingFactStatus.VALID).count() == 1

    grant_action(active_user, "ingestion_batch.retry", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)
    # Follow-up batch with only structural errors must not wipe prior valid facts.
    bad = CreateIngestionBatch(
        context=ctx,
        source_public_id=first.source.public_id,
        batch_key="KEEP-FAIL",
        source_type=DataSourceType.API,
        rows=[_row(external_record_key="BAD-ONLY", unit="", currency="")],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=bad.public_id).execute()
    ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=bad.public_id,
        idempotency_key="keep-fail",
    ).execute()
    RetryIngestionBatch(context=ctx, batch_public_id=bad.public_id).execute()
    assert OperatingFact.objects.filter(fact_status=OperatingFactStatus.VALID).count() == 1
    assert OperatingFact.objects.get().numeric_value == Decimal("1250.50")
