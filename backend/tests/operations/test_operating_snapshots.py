"""Immutable OperatingDataSnapshot freezes summary evidence with SHA-256."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import DataSourceType
from apps.integrations.services.data_sources import ConfigureOperatingDataSource
from apps.integrations.services.ingestion import CreateIngestionBatch, ValidateIngestionBatch
from apps.operations.errors import SnapshotImmutable
from apps.operations.models import (
    CalculationType,
    MetricDefinitionStatus,
    OperatingDataSnapshot,
)
from apps.operations.services.aggregations import RecalculateMetricAggregates
from apps.operations.services.data_snapshots import CreateOperatingDataSnapshot
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.application.command import CommandContext
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
        department_code="OPS-SNAP",
        name="Ops Snapshots",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-SNAP",
        name="Snapshot yogurt",
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
        sku_code="SKU-SNAP",
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
    return {"product": product, "sku": sku, "channel": channel}


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


def _seed_sales(*, user, department, grant_action, catalog) -> None:
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
        aggregation_rule={"by": ["SKU", "CHANNEL", "PRODUCT"]},
        window_definition={"granularity": "MONTH"},
        coverage_requirement={"minimum_rate": "0.8"},
        valid_from=timezone.now(),
    ).execute()
    published = PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()
    assert published.status == MetricDefinitionStatus.PUBLISHED

    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    grant_action(user, "ingestion_batch.create", "ingestion_batch")
    grant_action(user, "ingestion_batch.confirm", "ingestion_batch")
    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code="SNAP_SRC",
        name="SNAP_SRC",
        source_type=DataSourceType.API,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="SNAP-1",
        source_type=DataSourceType.API,
        rows=[
            {
                "external_record_key": "SNAP-ERP-1",
                "sku_code": catalog["sku"].sku_code,
                "channel_code": catalog["channel"].channel_code,
                "metric_code": "GROSS_SALES",
                "period_granularity": "MONTH",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "sales_amount": "250.00",
                "unit": "CNY",
                "currency": "CNY",
                "source_timestamp": "2026-02-01T10:00:00+00:00",
            }
        ],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()
    ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key="snap-confirm",
    ).execute()
    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": user.organization_id,
                "metric_code": "GROSS_SALES",
                "period_granularity": "MONTH",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            }
        ],
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_snapshot_freezes_scope_values_and_rejects_updates(
    active_user: User,
    ops_department: Department,
    catalog,
    grant_action,
) -> None:
    _seed_sales(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        catalog=catalog,
    )
    grant_action(active_user, "operating_fact.read", "operating_fact")
    ctx = CommandContext.for_actor(active_user)
    snapshot = CreateOperatingDataSnapshot(
        context=ctx,
        purpose="RETIREMENT_REVIEW",
        scope={
            "product_public_ids": [str(catalog["product"].public_id)],
            "sku_public_ids": [str(catalog["sku"].public_id)],
            "channel_public_ids": [str(catalog["channel"].public_id)],
        },
        periods=[
            {
                "period_granularity": "MONTH",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            }
        ],
        metric_codes=["GROSS_SALES"],
    ).execute()

    assert isinstance(snapshot, OperatingDataSnapshot)
    assert snapshot.purpose == "RETIREMENT_REVIEW"
    assert len(snapshot.content_hash) == 64
    assert snapshot.content_hash == snapshot.compute_content_hash()
    payload = snapshot.payload_json
    assert payload["scope"]["product_public_ids"] == [str(catalog["product"].public_id)]
    assert payload["scope"]["sku_public_ids"] == [str(catalog["sku"].public_id)]
    assert payload["scope"]["channel_public_ids"] == [str(catalog["channel"].public_id)]
    assert payload["periods"][0]["period_start"] == "2026-01-01"
    assert "GROSS_SALES" in payload["metric_codes"]
    metrics = payload["metrics"]
    assert len(metrics) >= 1
    sales = next(m for m in metrics if m["metric_code"] == "GROSS_SALES")
    assert Decimal(sales["value"]) == Decimal("250.00")
    assert "metric_definition_public_id" in sales
    assert "metric_version_number" in sales
    assert "coverage_rate" in sales
    assert "has_manual_value" in sales
    assert "threshold" in sales or "coverage_requirement" in sales
    assert sales["fact_ids"]
    assert sales["fact_summaries"]
    assert all("public_id" in f for f in sales["fact_summaries"])

    with pytest.raises(SnapshotImmutable):
        snapshot.purpose = "CHANGED"
        snapshot.save()

    reloaded = OperatingDataSnapshot.objects.get(pk=snapshot.pk)
    with pytest.raises(SnapshotImmutable):
        reloaded.payload_json = {"tampered": True}
        reloaded.save()
