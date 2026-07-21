"""Late fact/manual value triggers incremental signal recalculation."""

from __future__ import annotations

from datetime import date, timedelta
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
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    OperatingDataSnapshot,
    OperatingFact,
    RiskSignal,
    SignalRecalculation,
)
from apps.operations.services.aggregations import RecalculateMetricAggregates
from apps.operations.services.effective_values import CreateManualEffectiveValue
from apps.operations.services.ingestion import ConfirmOperatingIngestionBatch
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.risk_rules import (
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
)
from apps.operations.services.risk_signals import RecalculateAffectedSignals
from apps.platform.application.command import CommandContext
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
        department_code="OPS-RECALC",
        name="Ops Recalc",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RECALC",
        name="Recalc yogurt",
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
        sku_code="SKU-RECALC",
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


@pytest.mark.django_db(transaction=True)
def test_late_fact_and_manual_trigger_recalc_without_rewriting_history(
    organization, active_user, grant_action, catalog, ops_department
) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    grant_action(active_user, "ingestion_batch.confirm", "ingestion_batch")
    grant_action(active_user, "manual_effective_value.create", "operating_value")
    ctx = CommandContext.for_actor(active_user)

    metric = PublishMetricDefinition(
        context=ctx,
        metric_public_id=CreateMetricDefinitionDraft(
            context=ctx,
            metric_code="PRODUCTION_QTY",
            name="Production qty",
            value_type="DECIMAL",
            unit="EA",
            currency="",
            source_field_codes=["sales_amount"],
            calculation_type="SUM",
            aggregation_rule={"by": ["SKU", "CHANNEL"]},
            window_definition={"granularity": "QUARTER"},
            coverage_requirement={"minimum_rate": "0.5"},
            valid_from=timezone.now() - timedelta(days=400),
        )
        .execute()
        .public_id,
    ).execute()
    rule = PublishRiskRule(
        context=ctx,
        rule_public_id=CreateRiskRuleDraft(
            context=ctx,
            rule_code="QUARTER_SHELF_MIN_PROD",
            name="四分之一效期最低生产量",
            metric_codes=[metric.metric_code],
            evaluator_code=QUARTER_SHELF_LIFE_MIN_PRODUCTION,
            parameters_json={
                "min_production": "1000",
                "shelf_life_days": "120",
                "window_days": "90",
                "target_digestion_ratio": "1.0",
                "metric_code": metric.metric_code,
                "applicable_sku_codes": [catalog["sku"].sku_code],
                "applicable_channel_codes": [catalog["channel"].channel_code],
            },
            scope_type="SKU_CHANNEL",
            valid_from=timezone.now() - timedelta(days=400),
        )
        .execute()
        .public_id,
    ).execute()

    period_start, period_end = date(2025, 10, 1), date(2025, 12, 31)
    MetricAggregate.objects.create(
        organization=organization,
        grain_type=AggregateGrainType.SKU,
        grain_id=catalog["sku"].public_id,
        channel=catalog["channel"],
        channel_key=str(catalog["channel"].public_id),
        metric_definition=metric,
        period_granularity="QUARTER",
        period_start=period_start,
        period_end=period_end,
        value=Decimal("200"),
        unit="EA",
        status=AggregateStatus.OK,
        coverage_rate=Decimal("1.0"),
        source_count=1,
        has_manual_value=False,
        contributors_json=[],
        calculated_at=timezone.now(),
        calculation_run_id=uuid4(),
    )
    signal = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()[0]
    old_actual = signal.actual_value
    old_threshold = signal.threshold_value
    old_snapshot_id = signal.data_snapshot_id
    old_hash = signal.data_snapshot.content_hash

    source = ConfigureOperatingDataSource(
        context=ctx,
        source_code="ERP-RECALC",
        name="ERP",
        source_type=DataSourceType.API,
        owner_department_public_id=ops_department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="late-1",
        source_type=DataSourceType.API,
        rows=[
            {
                "external_record_key": "LATE-001",
                "sku_code": catalog["sku"].sku_code,
                "channel_code": catalog["channel"].channel_code,
                "sales_amount": "800",
                "metric_code": metric.metric_code,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "period_granularity": "QUARTER",
                "unit": "EA",
                "currency": "NA",
                "source_timestamp": timezone.now().isoformat(),
            }
        ],
    ).execute()
    ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()
    ConfirmOperatingIngestionBatch(
        context=ctx,
        batch_public_id=batch.public_id,
        idempotency_key="late-1-confirm",
        confirm_warnings=True,
    ).execute()
    fact = OperatingFact.objects.get(source_record_key="LATE-001")
    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": organization.id,
                "sku_public_id": str(catalog["sku"].public_id),
                "channel_public_id": str(catalog["channel"].public_id),
                "metric_code": metric.metric_code,
                "period_granularity": "QUARTER",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            }
        ],
    ).execute()

    recs = RecalculateAffectedSignals(fact_public_id=fact.public_id).execute()
    assert len(recs) >= 1
    recalc = SignalRecalculation.objects.filter(signal=signal).latest("created_at")
    assert recalc.old_actual_value == old_actual
    assert recalc.new_actual_value == Decimal("800")
    assert recalc.reason
    assert recalc.impact_summary

    signal.refresh_from_db()
    assert signal.actual_value == old_actual
    assert signal.threshold_value == old_threshold
    assert signal.data_snapshot_id == old_snapshot_id
    snap = OperatingDataSnapshot.objects.get(pk=old_snapshot_id)
    assert snap.content_hash == old_hash

    manual = CreateManualEffectiveValue(
        context=ctx,
        sku_public_id=catalog["sku"].public_id,
        channel_public_id=catalog["channel"].public_id,
        metric_definition_public_id=metric.public_id,
        period_granularity="QUARTER",
        period_start=period_start,
        period_end=period_end,
        numeric_value=Decimal("1500"),
        reason="Corrected late ERP gap",
    ).execute()
    RecalculateMetricAggregates(
        calculation_run_id=uuid4(),
        affected_keys=[
            {
                "organization_id": organization.id,
                "sku_public_id": str(catalog["sku"].public_id),
                "channel_public_id": str(catalog["channel"].public_id),
                "metric_code": metric.metric_code,
                "period_granularity": "QUARTER",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            }
        ],
    ).execute()
    RecalculateAffectedSignals(manual_value_public_id=manual.public_id).execute()
    assert SignalRecalculation.objects.filter(signal=signal).count() >= 2
    signal.refresh_from_db()
    assert signal.actual_value == old_actual
    assert RiskSignal.objects.filter(pk=signal.pk).count() == 1
