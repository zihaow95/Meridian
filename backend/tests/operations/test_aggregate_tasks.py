"""Celery aggregate task params are business keys only; MySQL is source of truth."""

from __future__ import annotations

from datetime import date
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
from apps.operations.models import CalculationType, MetricAggregate, MetricDefinitionStatus
from apps.operations.queries.operating_summary import QuerySkuOperatingSummary
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.tasks import recalculate_metric_aggregates_task
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
        department_code="OPS-TASK",
        name="Ops Tasks",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-TASK",
        name="Task yogurt",
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
        sku_code="SKU-TASK",
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


def _seed(*, user, department, grant_action, catalog) -> None:
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
    assert (
        PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute().status
        == MetricDefinitionStatus.PUBLISHED
    )
    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    grant_action(user, "ingestion_batch.create", "ingestion_batch")
    grant_action(user, "ingestion_batch.confirm", "ingestion_batch")
    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code="TASK_SRC",
        name="TASK_SRC",
        source_type=DataSourceType.API,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content={
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
        },
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="TASK-1",
        source_type=DataSourceType.API,
        rows=[
            {
                "external_record_key": "TASK-1",
                "sku_code": catalog["sku"].sku_code,
                "channel_code": catalog["channel"].channel_code,
                "metric_code": "GROSS_SALES",
                "period_granularity": "MONTH",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "sales_amount": "77.00",
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
        idempotency_key="task-confirm",
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_celery_task_accepts_only_run_id_and_business_keys(
    active_user: User,
    ops_department: Department,
    catalog,
    grant_action,
) -> None:
    _seed(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        catalog=catalog,
    )
    run_id = str(uuid4())
    affected_keys = [
        {
            "organization_id": active_user.organization_id,
            "metric_code": "GROSS_SALES",
            "period_granularity": "MONTH",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        }
    ]

    # Synchronous call — params must not include fact payloads / numeric detail rows
    result = recalculate_metric_aggregates_task.apply(
        args=(run_id, affected_keys),
    ).get()
    assert result >= 1
    assert MetricAggregate.objects.filter(calculation_run_id=run_id).exists()

    grant_action(active_user, "operating_fact.read", "operating_fact")
    summary = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    channel_row = next(
        i for i in summary.items if i.channel_public_id == catalog["channel"].public_id
    )
    assert channel_row.value == Decimal("77.00")

    # Query path reads aggregates only (bounded), not unbounded fact scans for the summary value
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        QuerySkuOperatingSummary(
            context=CommandContext.for_actor(active_user),
            sku_public_id=catalog["sku"].public_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            period_granularity="MONTH",
            metric_codes=["GROSS_SALES"],
            include_drilldown=False,
        ).execute()
    sql = " ".join(q["sql"] for q in ctx.captured_queries).lower()
    assert "operations_metric_aggregate" in sql
    assert "operations_operating_fact" not in sql
