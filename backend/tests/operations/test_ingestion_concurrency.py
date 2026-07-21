"""Two-connection concurrency for ingestion confirm and manual values."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection, IntegrityError
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
    OperatingFact,
    OperatingFactStatus,
)
from apps.operations.services.effective_values import CreateManualEffectiveValue
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.application.command import CommandContext
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import (
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKU,
    SKUStatus,
)


@pytest.fixture
def ops_department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="OPS-CONC",
        name="Ops Concurrency",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def sku_channel(organization: Organization, active_user: User) -> tuple[SKU, ChannelConfiguration]:
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-CONC",
        name="Concurrency yogurt",
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


def _mapping_content() -> dict:
    return {
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


@pytest.mark.django_db(transaction=True)
def test_concurrent_confirm_produces_one_fact_set_one_audit_one_outbox(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    del sku_channel
    _publish_metric(active_user, grant_action)
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    grant_action(active_user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)
    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code="CONC_SRC",
        name="CONC_SRC",
        source_type=DataSourceType.API,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="CONC-BATCH",
        source_type=DataSourceType.API,
        rows=[_row()],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def _confirm(key: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            ConfirmOperatingIngestionBatch(
                context=CommandContext.for_actor(active_user),
                batch_public_id=batch.public_id,
                idempotency_key=key,
            ).execute()
            results.append(f"ok:{key}")
        except Exception as exc:  # noqa: BLE001
            results.append(f"other:{type(exc).__name__}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_confirm, args=("conc-a",)),
        threading.Thread(target=_confirm, args=("conc-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert any(item.startswith("ok:") for item in results)
    assert OperatingFact.objects.filter(fact_status=OperatingFactStatus.VALID).count() == 1
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
def test_concurrent_manual_create_leaves_one_active(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    del ops_department
    sku, channel = sku_channel
    metric = _publish_metric(active_user, grant_action)
    grant_action(active_user, "manual_effective_value.create", "operating_value")

    results: list[str] = []
    barrier = threading.Barrier(2)

    def _create(amount: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            CreateManualEffectiveValue(
                context=CommandContext.for_actor(active_user),
                sku_public_id=sku.public_id,
                channel_public_id=channel.public_id,
                metric_definition_public_id=metric.public_id,
                period_granularity="MONTH",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                numeric_value=Decimal(amount),
                reason=f"Concurrent {amount}",
            ).execute()
            results.append(f"ok:{amount}")
        except IntegrityError:
            results.append("conflict:IntegrityError")
        except Exception as exc:  # noqa: BLE001
            results.append(f"other:{type(exc).__name__}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_create, args=("111.00",)),
        threading.Thread(target=_create, args=("222.00",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert any(item.startswith("ok:") for item in results)
    assert (
        ManualEffectiveValue.objects.filter(
            sku=sku,
            channel=channel,
            metric_definition=metric,
            status=ManualEffectiveValueStatus.ACTIVE,
            active_slot=1,
        ).count()
        == 1
    )
