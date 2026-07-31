"""Risk rules: published-only evaluation, coverage gate, controlled evaluators."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    MetricDefinitionStatus,
    RiskRuleStatus,
    RiskSignal,
)
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.platform.api.errors import ValidationFailedError
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
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-RISK",
        name="Risk yogurt",
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
        sku_code="SKU-RISK",
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


def _publish_metric(active_user: User, grant_action, *, coverage_min: str = "0.8"):
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    draft = CreateMetricDefinitionDraft(
        context=ctx,
        metric_code="PRODUCTION_QTY",
        name="Production qty",
        value_type="DECIMAL",
        unit="EA",
        currency="",
        source_field_codes=["production_qty"],
        calculation_type="SUM",
        aggregation_rule={"by": ["SKU", "CHANNEL"]},
        window_definition={"granularity": "QUARTER"},
        coverage_requirement={"minimum_rate": coverage_min},
        valid_from=timezone.now() - timedelta(days=400),
    ).execute()
    return PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()


def _seed_aggregate(
    *,
    organization: Organization,
    metric,
    catalog,
    period_start: date,
    period_end: date,
    value: Decimal,
    status: str = AggregateStatus.OK,
    coverage_rate: Decimal = Decimal("1.0"),
):
    return MetricAggregate.objects.create(
        organization=organization,
        grain_type=AggregateGrainType.SKU,
        grain_id=catalog["sku"].public_id,
        channel=catalog["channel"],
        channel_key=str(catalog["channel"].public_id),
        metric_definition=metric,
        period_granularity="QUARTER",
        period_start=period_start,
        period_end=period_end,
        value=value,
        unit="EA",
        status=status,
        coverage_rate=coverage_rate,
        source_count=1,
        has_manual_value=False,
        contributors_json=[],
        calculated_at=timezone.now(),
        calculation_run_id=uuid4(),
    )


def _publish_quarter_rule(active_user: User, grant_action, catalog, metric, **param_overrides):
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    params = {
        "min_production": "1000",
        "shelf_life_days": "120",
        "window_days": "90",
        "target_digestion_ratio": "1.0",
        "metric_code": metric.metric_code,
        "applicable_sku_codes": [catalog["sku"].sku_code],
        "applicable_channel_codes": [catalog["channel"].channel_code],
    }
    params.update(param_overrides)
    draft = CreateRiskRuleDraft(
        context=ctx,
        rule_code="QUARTER_SHELF_MIN_PROD",
        name="四分之一效期最低生产量",
        metric_codes=[metric.metric_code],
        evaluator_code=QUARTER_SHELF_LIFE_MIN_PRODUCTION,
        parameters_json=params,
        scope_type="SKU_CHANNEL",
        valid_from=timezone.now() - timedelta(days=400),
    ).execute()
    return PublishRiskRule(context=ctx, rule_public_id=draft.public_id).execute()


@pytest.mark.django_db(transaction=True)
def test_evaluate_skips_draft_rules_and_open_windows(
    organization, active_user, grant_action, catalog
) -> None:
    metric = _publish_metric(active_user, grant_action)
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    draft = CreateRiskRuleDraft(
        context=ctx,
        rule_code="DRAFT_ONLY",
        name="Draft",
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
        valid_from=timezone.now(),
    ).execute()
    assert draft.status == RiskRuleStatus.DRAFT

    period_start = date(2026, 1, 1)
    period_end = date(2026, 3, 31)
    _seed_aggregate(
        organization=organization,
        metric=metric,
        catalog=catalog,
        period_start=period_start,
        period_end=period_end,
        value=Decimal("100"),
    )
    created = EvaluateRiskRules(
        rule_version_id=draft.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()
    assert created == []
    assert RiskSignal.objects.count() == 0

    published = _publish_quarter_rule(active_user, grant_action, catalog, metric)
    future_end = date.today() + timedelta(days=10)
    future_start = future_end - timedelta(days=89)
    _seed_aggregate(
        organization=organization,
        metric=metric,
        catalog=catalog,
        period_start=future_start,
        period_end=future_end,
        value=Decimal("100"),
    )
    created = EvaluateRiskRules(
        rule_version_id=published.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": future_start,
            "period_end": future_end,
        },
    ).execute()
    assert created == []
    assert RiskSignal.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_insufficient_coverage_does_not_create_normal_or_risk_signal(
    organization, active_user, grant_action, catalog
) -> None:
    metric = _publish_metric(active_user, grant_action)
    rule = _publish_quarter_rule(active_user, grant_action, catalog, metric)
    period_start = date(2025, 10, 1)
    period_end = date(2025, 12, 31)
    agg = _seed_aggregate(
        organization=organization,
        metric=metric,
        catalog=catalog,
        period_start=period_start,
        period_end=period_end,
        value=Decimal("50"),
        status=AggregateStatus.INSUFFICIENT,
        coverage_rate=Decimal("0.2"),
    )
    created = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()
    assert created == []
    assert RiskSignal.objects.count() == 0
    agg.refresh_from_db()
    assert agg.status == AggregateStatus.INSUFFICIENT


@pytest.mark.django_db(transaction=True)
def test_quarter_shelf_life_evaluator_exposes_version_params_formula_and_snapshot(
    organization, active_user, grant_action, catalog
) -> None:
    metric = _publish_metric(active_user, grant_action)
    rule = _publish_quarter_rule(active_user, grant_action, catalog, metric)
    period_start = date(2025, 10, 1)
    period_end = date(2025, 12, 31)
    _seed_aggregate(
        organization=organization,
        metric=metric,
        catalog=catalog,
        period_start=period_start,
        period_end=period_end,
        value=Decimal("200"),
    )
    created = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()
    assert len(created) == 1
    signal = created[0]
    assert signal.rule_version_id == rule.id
    assert signal.actual_value == Decimal("200")
    assert signal.threshold_value == Decimal("1000")
    assert signal.period_start == period_start
    assert signal.period_end == period_end
    formula = signal.formula_snapshot
    assert formula["evaluator_code"] == QUARTER_SHELF_LIFE_MIN_PRODUCTION
    assert formula["rule_version_number"] == rule.version_number
    assert formula["parameters"]["min_production"] == "1000"
    assert "formula" in formula
    assert signal.data_snapshot_id is not None
    snapshot = signal.data_snapshot
    assert snapshot.purpose == "risk_signal"
    assert metric.metric_code in snapshot.metric_codes


@pytest.mark.django_db(transaction=True)
def test_unregistered_evaluator_code_rejected_on_publish(
    active_user, grant_action, catalog
) -> None:
    metric = _publish_metric(active_user, grant_action)
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    with pytest.raises(ValidationFailedError) as exc:
        CreateRiskRuleDraft(
            context=ctx,
            rule_code="BAD_EVAL",
            name="Bad",
            metric_codes=[metric.metric_code],
            evaluator_code="arbitrary_python_eval",
            parameters_json={"min_production": "1"},
            scope_type="SKU_CHANNEL",
            valid_from=timezone.now(),
        ).execute()
    assert (
        "evaluator_code" in str(exc.value.message).lower()
        or "evaluator" in str(exc.value.message).lower()
    )


@pytest.mark.django_db(transaction=True)
def test_published_risk_rule_is_immutable(active_user, grant_action, catalog) -> None:
    from apps.operations.models import PublishedRiskRuleImmutable

    metric = _publish_metric(active_user, grant_action)
    rule = _publish_quarter_rule(active_user, grant_action, catalog, metric)
    assert (
        rule.status == MetricDefinitionStatus.PUBLISHED or rule.status == RiskRuleStatus.PUBLISHED
    )
    with pytest.raises(PublishedRiskRuleImmutable):
        rule.name = "Tampered"
        rule.save()
