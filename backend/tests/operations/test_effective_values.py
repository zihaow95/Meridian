"""Manual effective values and ResolveEffectiveOperatingValue priority."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent, AuditResult
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import DataSourceType
from apps.integrations.services.data_sources import ConfigureOperatingDataSource
from apps.integrations.services.ingestion import CreateIngestionBatch, ValidateIngestionBatch
from apps.operations.models import (
    CalculationType,
    ManualEffectiveValue,
    ManualEffectiveValueStatus,
    OperatingFactStatus,
)
from apps.operations.services.effective_values import (
    CreateManualEffectiveValue,
    ModifyManualEffectiveValue,
    ResolveEffectiveOperatingValue,
    RevokeManualEffectiveValue,
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
        department_code="OPS-EFF",
        name="Ops Effective",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def sku_channel(organization: Organization, active_user: User) -> tuple[SKU, ChannelConfiguration]:
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-EFF",
        name="Effective yogurt",
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


def _mapping_content(*, priority: int) -> dict:
    return {
        "source_priority": priority,
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


def _publish_metric(user: User, grant_action):
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
    return PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()


def _import_fact(
    *,
    user,
    department,
    grant_action,
    source_code: str,
    priority: int,
    amount: str,
    record_key: str,
    timestamp: str,
):
    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    grant_action(user, "ingestion_batch.create", "ingestion_batch")
    grant_action(user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(user)
    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code=source_code,
        name=source_code,
        source_type=DataSourceType.API,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(priority=priority),
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key=f"{source_code}-B1",
        source_type=DataSourceType.API,
        rows=[
            _row(
                external_record_key=record_key,
                sales_amount=amount,
                source_timestamp=timestamp,
            )
        ],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()
    ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key=f"{source_code}-confirm",
    ).execute()
    return source


@pytest.mark.django_db(transaction=True)
def test_resolve_prefers_active_manual_then_source_priority_and_timestamp(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    sku, channel = sku_channel
    grant_action(active_user, "operating_fact.read", "operating_fact")
    metric = _publish_metric(active_user, grant_action)
    _import_fact(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="LOW_PRIO",
        priority=5,
        amount="100.00",
        record_key="LOW-1",
        timestamp="2026-02-10T10:00:00+00:00",
    )
    _import_fact(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="HIGH_PRIO",
        priority=20,
        amount="200.00",
        record_key="HIGH-1",
        timestamp="2026-02-01T10:00:00+00:00",
    )

    resolved = ResolveEffectiveOperatingValue(
        context=CommandContext.for_actor(active_user),
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_code="GROSS_SALES",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
    ).execute()
    assert resolved.is_manual is False
    assert resolved.numeric_value == Decimal("200.00")
    assert resolved.coverage_status == "SUFFICIENT"

    grant_action(active_user, "manual_effective_value.create", "operating_value")
    manual = CreateManualEffectiveValue(
        context=CommandContext.for_actor(active_user),
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_definition_public_id=metric.public_id,
        period_granularity="MONTH",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        numeric_value=Decimal("333.00"),
        reason="Supervisor adjustment",
    ).execute()
    assert manual.status == ManualEffectiveValueStatus.ACTIVE
    assert manual.active_slot == 1

    resolved_manual = ResolveEffectiveOperatingValue(
        context=CommandContext.for_actor(active_user),
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_code="GROSS_SALES",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
    ).execute()
    assert resolved_manual.is_manual is True
    assert resolved_manual.numeric_value == Decimal("333.00")
    assert (
        AuditEvent.objects.filter(
            action_code="manual_effective_value.create",
            result=AuditResult.SUCCESS,
        ).count()
        == 1
    )
    assert OutboxEvent.objects.filter(event_type="operating_value.overridden").count() == 1


@pytest.mark.django_db(transaction=True)
def test_modify_appends_version_and_revoke_restores_source_fact(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    sku, channel = sku_channel
    grant_action(active_user, "operating_fact.read", "operating_fact")
    metric = _publish_metric(active_user, grant_action)
    _import_fact(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="SRC_A",
        priority=10,
        amount="1250.50",
        record_key="ERP-001",
        timestamp="2026-02-01T10:00:00+00:00",
    )
    grant_action(active_user, "manual_effective_value.create", "operating_value")
    grant_action(active_user, "manual_effective_value.modify", "operating_value")
    grant_action(active_user, "manual_effective_value.revoke", "operating_value")
    ctx = CommandContext.for_actor(active_user)

    first = CreateManualEffectiveValue(
        context=ctx,
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_definition_public_id=metric.public_id,
        period_granularity="MONTH",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        numeric_value=Decimal("400.00"),
        reason="First override",
    ).execute()
    second = ModifyManualEffectiveValue(
        context=ctx,
        manual_value_public_id=first.public_id,
        numeric_value=Decimal("450.00"),
        reason="Adjusted override",
    ).execute()
    first.refresh_from_db()
    assert first.status == ManualEffectiveValueStatus.SUPERSEDED
    assert first.active_slot is None
    assert second.status == ManualEffectiveValueStatus.ACTIVE
    assert second.active_slot == 1
    assert second.numeric_value == Decimal("450.00")
    assert ManualEffectiveValue.objects.count() == 2

    RevokeManualEffectiveValue(
        context=ctx,
        manual_value_public_id=second.public_id,
        reason="Restore source",
    ).execute()
    second.refresh_from_db()
    assert second.status == ManualEffectiveValueStatus.REVOKED
    assert second.active_slot is None
    assert (
        ManualEffectiveValue.objects.filter(
            sku=sku,
            channel=channel,
            metric_definition=metric,
            active_slot=1,
        ).count()
        == 0
    )

    restored = ResolveEffectiveOperatingValue(
        context=ctx,
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_code="GROSS_SALES",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
    ).execute()
    assert restored.is_manual is False
    assert restored.numeric_value == Decimal("1250.50")
    assert restored.fact_status == OperatingFactStatus.VALID


@pytest.mark.django_db(transaction=True)
def test_resolve_returns_insufficient_when_no_fact_or_manual(
    active_user: User,
    sku_channel,
    grant_action,
) -> None:
    sku, channel = sku_channel
    grant_action(active_user, "operating_fact.read", "operating_fact")
    _publish_metric(active_user, grant_action)
    resolved = ResolveEffectiveOperatingValue(
        context=CommandContext.for_actor(active_user),
        sku_public_id=sku.public_id,
        channel_public_id=channel.public_id,
        metric_code="GROSS_SALES",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
    ).execute()
    assert resolved.coverage_status == "INSUFFICIENT"
    assert resolved.numeric_value is None


@pytest.mark.django_db(transaction=True)
def test_resolve_denies_without_operating_fact_read(
    active_user: User,
    sku_channel,
    grant_action,
) -> None:
    from apps.platform.api.errors import PermissionDeniedError

    sku, channel = sku_channel
    _publish_metric(active_user, grant_action)
    with pytest.raises(PermissionDeniedError):
        ResolveEffectiveOperatingValue(
            context=CommandContext.for_actor(active_user),
            sku_public_id=sku.public_id,
            channel_public_id=channel.public_id,
            metric_code="GROSS_SALES",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            period_granularity="MONTH",
        ).execute()
