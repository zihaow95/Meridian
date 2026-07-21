"""Metric aggregates: SKU/channel base grain, rollups, calculators, rebuild."""

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
from apps.operations.models import (
    CalculationType,
    MetricAggregate,
    MetricDefinitionStatus,
    OperatingFact,
)
from apps.operations.queries.operating_summary import (
    QueryProductOperatingSummary,
    QuerySkuOperatingSummary,
)
from apps.operations.services.aggregations import RecalculateMetricAggregates
from apps.operations.services.effective_values import CreateManualEffectiveValue
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
        department_code="OPS-AGG",
        name="Ops Aggregates",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-AGG",
        name="Aggregate yogurt",
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
    sku_a = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-A",
        name="Cup A",
        specification="120g",
        status=SKUStatus.ACTIVE,
    )
    sku_b = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-B",
        name="Cup B",
        specification="200g",
        status=SKUStatus.ACTIVE,
    )
    ch_a1 = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku_a,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    ch_a2 = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku_a,
        channel_code="JD",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    ch_b1 = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku_b,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    ch_b2 = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku_b,
        channel_code="JD",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    return {
        "product": product,
        "sku_a": sku_a,
        "sku_b": sku_b,
        "ch_a1": ch_a1,
        "ch_a2": ch_a2,
        "ch_b1": ch_b1,
        "ch_b2": ch_b2,
    }


def _mapping_content(*, priority: int = 10) -> dict:
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
        "sku_code": "SKU-A",
        "channel_code": "TMALL",
        "metric_code": "GROSS_SALES",
        "period_granularity": "MONTH",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "sales_amount": "100.00",
        "unit": "CNY",
        "currency": "CNY",
        "source_timestamp": "2026-02-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _publish_metric(
    user: User,
    grant_action,
    *,
    metric_code: str = "GROSS_SALES",
    calculation_type: str = CalculationType.SUM,
    parameters_json: dict | None = None,
    coverage_minimum: str = "0.8",
    unit: str = "CNY",
    currency: str = "CNY",
):
    grant_action(user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(user)
    draft = CreateMetricDefinitionDraft(
        context=ctx,
        metric_code=metric_code,
        name=metric_code,
        value_type="DECIMAL",
        unit=unit,
        currency=currency,
        source_field_codes=["sales_amount"],
        calculation_type=calculation_type,
        aggregation_rule={"by": ["SKU", "CHANNEL", "PRODUCT"]},
        window_definition={"granularity": "MONTH"},
        coverage_requirement={"minimum_rate": coverage_minimum},
        parameters_json=parameters_json or {},
        valid_from=timezone.now(),
    ).execute()
    published = PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()
    assert published.status == MetricDefinitionStatus.PUBLISHED
    return published


def _import_rows(*, user, department, grant_action, rows, batch_key: str):
    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    grant_action(user, "ingestion_batch.create", "ingestion_batch")
    grant_action(user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(user)
    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code=f"SRC-{batch_key}",
        name=f"SRC-{batch_key}",
        source_type=DataSourceType.API,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key=batch_key,
        source_type=DataSourceType.API,
        rows=rows,
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()
    ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key=f"{batch_key}-confirm",
    ).execute()


def _period_key() -> dict:
    return {
        "period_granularity": "MONTH",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
    }


@pytest.mark.django_db(transaction=True)
def test_sum_average_last_and_ratio_recompute_from_parts(
    active_user: User,
    ops_department: Department,
    catalog,
    grant_action,
) -> None:
    _publish_metric(
        active_user, grant_action, metric_code="GROSS_SALES", calculation_type=CalculationType.SUM
    )
    _publish_metric(
        active_user,
        grant_action,
        metric_code="UNITS_SOLD",
        calculation_type=CalculationType.AVERAGE,
    )
    _publish_metric(
        active_user, grant_action, metric_code="LAST_PRICE", calculation_type=CalculationType.LAST
    )
    _publish_metric(
        active_user,
        grant_action,
        metric_code="GROSS_PROFIT",
        calculation_type=CalculationType.SUM,
    )
    _publish_metric(
        active_user,
        grant_action,
        metric_code="MARGIN_RATIO",
        calculation_type=CalculationType.RATIO,
        parameters_json={
            "numerator_metric_code": "GROSS_PROFIT",
            "denominator_metric_code": "GROSS_SALES",
        },
        unit="RATIO",
        currency="",
    )

    _import_rows(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        batch_key="SUM1",
        rows=[
            _row(
                external_record_key="S-A1",
                sku_code="SKU-A",
                channel_code="TMALL",
                metric_code="GROSS_SALES",
                sales_amount="100.00",
            ),
            _row(
                external_record_key="S-A2",
                sku_code="SKU-A",
                channel_code="JD",
                metric_code="GROSS_SALES",
                sales_amount="50.00",
            ),
            _row(
                external_record_key="S-B1",
                sku_code="SKU-B",
                channel_code="TMALL",
                metric_code="GROSS_SALES",
                sales_amount="50.00",
            ),
            _row(
                external_record_key="U-A1",
                sku_code="SKU-A",
                channel_code="TMALL",
                metric_code="UNITS_SOLD",
                sales_amount="10.00",
                unit="EA",
                currency="EA",
            ),
            _row(
                external_record_key="U-A2",
                sku_code="SKU-A",
                channel_code="JD",
                metric_code="UNITS_SOLD",
                sales_amount="30.00",
                unit="EA",
                currency="EA",
            ),
            _row(
                external_record_key="P-A1",
                sku_code="SKU-A",
                channel_code="TMALL",
                metric_code="LAST_PRICE",
                sales_amount="9.00",
                source_timestamp="2026-01-10T10:00:00+00:00",
            ),
            _row(
                external_record_key="P-A2",
                sku_code="SKU-A",
                channel_code="JD",
                metric_code="LAST_PRICE",
                sales_amount="12.00",
                source_timestamp="2026-01-20T10:00:00+00:00",
            ),
            _row(
                external_record_key="GP-A1",
                sku_code="SKU-A",
                channel_code="TMALL",
                metric_code="GROSS_PROFIT",
                sales_amount="40.00",
            ),
            _row(
                external_record_key="GP-A2",
                sku_code="SKU-A",
                channel_code="JD",
                metric_code="GROSS_PROFIT",
                sales_amount="10.00",
            ),
        ],
    )

    run_id = uuid4()
    RecalculateMetricAggregates(
        calculation_run_id=run_id,
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                **_period_key(),
            },
            {
                "organization_id": active_user.organization_id,
                "metric_code": "UNITS_SOLD",
                **_period_key(),
            },
            {
                "organization_id": active_user.organization_id,
                "metric_code": "LAST_PRICE",
                **_period_key(),
            },
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_PROFIT",
                **_period_key(),
            },
            {
                "organization_id": active_user.organization_id,
                "metric_code": "MARGIN_RATIO",
                **_period_key(),
            },
        ],
    ).execute()

    grant_action(active_user, "operating_fact.read", "operating_fact")
    ctx = CommandContext.for_actor(active_user)
    sku_summary = QuerySkuOperatingSummary(
        context=ctx,
        sku_public_id=catalog["sku_a"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES", "UNITS_SOLD", "LAST_PRICE", "MARGIN_RATIO"],
    ).execute()
    by_metric = {
        item.metric_code: item for item in sku_summary.items if item.channel_public_id is None
    }

    assert by_metric["GROSS_SALES"].value == Decimal("150.00")
    assert by_metric["GROSS_SALES"].status == "OK"
    assert by_metric["UNITS_SOLD"].value == Decimal("20.00")
    assert by_metric["LAST_PRICE"].value == Decimal("12.00")
    # RATIO recomputes 50/150, not average of channel ratios (0.4 and 0.2 → 0.3)
    assert by_metric["MARGIN_RATIO"].value == (Decimal("50") / Decimal("150")).quantize(
        Decimal("0.000001")
    )

    product_summary = QueryProductOperatingSummary(
        context=ctx,
        product_public_id=catalog["product"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    product_sales = next(i for i in product_summary.items if i.metric_code == "GROSS_SALES")
    assert product_sales.value == Decimal("200.00")
    assert product_sales.grain_type == "PRODUCT"


@pytest.mark.django_db(transaction=True)
def test_not_comparable_insufficient_and_manual_flag(
    active_user: User,
    ops_department: Department,
    catalog,
    grant_action,
) -> None:
    metric = _publish_metric(
        active_user,
        grant_action,
        coverage_minimum="0.9",
    )
    _import_rows(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        batch_key="NC1",
        rows=[
            _row(
                external_record_key="CNY-1",
                sku_code="SKU-A",
                channel_code="TMALL",
                sales_amount="100.00",
                currency="CNY",
                unit="CNY",
            ),
            _row(
                external_record_key="USD-1",
                sku_code="SKU-A",
                channel_code="JD",
                sales_amount="50.00",
                currency="USD",
                unit="USD",
            ),
        ],
    )

    run_id = uuid4()
    RecalculateMetricAggregates(
        calculation_run_id=run_id,
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                **_period_key(),
            }
        ],
    ).execute()

    grant_action(active_user, "operating_fact.read", "operating_fact")
    sku_summary = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_a"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    rolled = next(i for i in sku_summary.items if i.channel_public_id is None)
    assert rolled.status == "NOT_COMPARABLE"
    assert rolled.value is None

    # Only one of two expected channels for SKU-B → INSUFFICIENT when coverage < 0.9
    _import_rows(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        batch_key="INS1",
        rows=[
            _row(
                external_record_key="B-ONLY",
                sku_code="SKU-B",
                channel_code="TMALL",
                sales_amount="80.00",
            ),
        ],
    )
    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                "sku_public_id": str(catalog["sku_b"].public_id),
                **_period_key(),
            }
        ],
    ).execute()
    sku_b_summary = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_b"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    sku_b_roll = next(i for i in sku_b_summary.items if i.channel_public_id is None)
    assert sku_b_roll.status == "INSUFFICIENT"
    assert sku_b_roll.coverage_rate < Decimal("0.9")

    grant_action(active_user, "manual_effective_value.create", "operating_value")
    CreateManualEffectiveValue(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_b"].public_id,
        channel_public_id=catalog["ch_b1"].public_id,
        metric_definition_public_id=metric.public_id,
        period_granularity="MONTH",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        numeric_value=Decimal("99.00"),
        reason="Supervisor override",
    ).execute()
    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                "sku_public_id": str(catalog["sku_b"].public_id),
                **_period_key(),
            }
        ],
    ).execute()
    after_manual = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_b"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    channel_row = next(
        i for i in after_manual.items if i.channel_public_id == catalog["ch_b1"].public_id
    )
    assert channel_row.value == Decimal("99.00")
    assert channel_row.has_manual_value is True


@pytest.mark.django_db(transaction=True)
def test_drilldown_and_rebuild_from_facts_without_mutating_facts(
    active_user: User,
    ops_department: Department,
    catalog,
    grant_action,
) -> None:
    _publish_metric(active_user, grant_action)
    _import_rows(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        batch_key="DRILL1",
        rows=[
            _row(
                external_record_key="D1",
                sku_code="SKU-A",
                channel_code="TMALL",
                sales_amount="40.00",
            ),
            _row(
                external_record_key="D2", sku_code="SKU-A", channel_code="JD", sales_amount="60.00"
            ),
        ],
    )
    fact_ids_before = set(OperatingFact.objects.values_list("public_id", flat=True))
    fact_values_before = list(
        OperatingFact.objects.order_by("id").values_list("numeric_value", "fact_status")
    )

    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                **_period_key(),
            }
        ],
    ).execute()
    assert MetricAggregate.objects.exists()

    grant_action(active_user, "operating_fact.read", "operating_fact")
    summary = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_a"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
        include_drilldown=True,
    ).execute()
    rolled = next(i for i in summary.items if i.channel_public_id is None)
    assert rolled.value == Decimal("100.00")
    assert len(rolled.contributors) == 2
    contributor_ids = {c["public_id"] for c in rolled.contributors}
    assert contributor_ids <= {str(x) for x in fact_ids_before}

    deleted = MetricAggregate.objects.all().delete()
    assert deleted[0] > 0
    assert set(OperatingFact.objects.values_list("public_id", flat=True)) == fact_ids_before
    assert (
        list(OperatingFact.objects.order_by("id").values_list("numeric_value", "fact_status"))
        == fact_values_before
    )

    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": active_user.organization_id,
                "metric_code": "GROSS_SALES",
                **_period_key(),
            }
        ],
    ).execute()
    rebuilt = QuerySkuOperatingSummary(
        context=CommandContext.for_actor(active_user),
        sku_public_id=catalog["sku_a"].public_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        period_granularity="MONTH",
        metric_codes=["GROSS_SALES"],
    ).execute()
    rebuilt_roll = next(i for i in rebuilt.items if i.channel_public_id is None)
    assert rebuilt_roll.value == Decimal("100.00")
    assert set(OperatingFact.objects.values_list("public_id", flat=True)) == fact_ids_before
