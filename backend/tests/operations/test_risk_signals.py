"""Risk signal lifecycle: uniqueness, status transitions, permissions."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.authorization.models.role import DataSensitivityLevel
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    MonitoringScopeType,
    RiskSignal,
    RiskSignalStatus,
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
from apps.operations.services.risk_signals import CloseRiskSignal, MarkRiskSignalViewed
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
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
from apps.projects.models import Project


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-SIG",
        name="Signal yogurt",
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
        sku_code="SKU-SIG",
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
    return {"product": product, "version": version, "sku": sku, "channel": channel}


def _metric_and_rule(active_user, grant_action, catalog):
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
        coverage_requirement={"minimum_rate": "0.8"},
        valid_from=timezone.now() - timedelta(days=400),
    ).execute()
    metric = PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()
    rule_draft = CreateRiskRuleDraft(
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
    ).execute()
    rule = PublishRiskRule(context=ctx, rule_public_id=rule_draft.public_id).execute()
    return metric, rule


def _seed_ok_aggregate(organization, metric, catalog, period_start, period_end, value="200"):
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
        value=Decimal(value),
        unit="EA",
        status=AggregateStatus.OK,
        coverage_rate=Decimal("1.0"),
        source_count=1,
        has_manual_value=False,
        contributors_json=[],
        calculated_at=timezone.now(),
        calculation_run_id=uuid4(),
    )


@pytest.mark.django_db(transaction=True)
def test_unique_rule_scope_period_and_new_period_creates_new_signal(
    organization, active_user, grant_action, catalog
) -> None:
    metric, rule = _metric_and_rule(active_user, grant_action, catalog)
    p1_start, p1_end = date(2025, 7, 1), date(2025, 9, 30)
    p2_start, p2_end = date(2025, 10, 1), date(2025, 12, 31)
    _seed_ok_aggregate(organization, metric, catalog, p1_start, p1_end)
    _seed_ok_aggregate(organization, metric, catalog, p2_start, p2_end)

    first = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={"period_granularity": "QUARTER", "period_start": p1_start, "period_end": p1_end},
    ).execute()
    again = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={"period_granularity": "QUARTER", "period_start": p1_start, "period_end": p1_end},
    ).execute()
    second = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={"period_granularity": "QUARTER", "period_start": p2_start, "period_end": p2_end},
    ).execute()

    assert len(first) == 1
    assert again == first or (len(again) == 1 and again[0].public_id == first[0].public_id)
    assert RiskSignal.objects.filter(period_start=p1_start).count() == 1
    assert len(second) == 1
    assert second[0].public_id != first[0].public_id
    assert RiskSignal.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_mark_viewed_and_close_with_reason_keeps_evidence(
    organization, active_user, another_active_user, grant_action, catalog, project: Project
) -> None:
    metric, rule = _metric_and_rule(active_user, grant_action, catalog)
    period_start, period_end = date(2025, 10, 1), date(2025, 12, 31)
    _seed_ok_aggregate(organization, metric, catalog, period_start, period_end)
    signals = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()
    signal = signals[0]
    snapshot_id = signal.data_snapshot_id
    actual = signal.actual_value

    # Assign supervisor on product scope
    assert catalog["product"].id is not None
    # Prefer assigning via monitoring on catalog product version

    # Create a lightweight scope using existing project fixture product mismatch —
    # InitializeMonitoringScope needs project+product_version; use catalog version with project
    # only if product matches. Fall back to grant_action for close/read.
    grant_action(another_active_user, "risk_signal.read", "risk_signal")
    grant_action(another_active_user, "risk_signal.close", "risk_signal")

    viewed = MarkRiskSignalViewed(
        context=CommandContext.for_actor(another_active_user),
        signal_public_id=signal.public_id,
    ).execute()
    assert viewed.status == RiskSignalStatus.VIEWED

    closed = CloseRiskSignal(
        context=CommandContext.for_actor(another_active_user),
        signal_public_id=signal.public_id,
        reason="Seasonal demand recovered",
    ).execute()
    assert closed.status == RiskSignalStatus.CLOSED
    assert closed.closed_reason == "Seasonal demand recovered"
    assert closed.closed_by_id == another_active_user.id
    assert closed.data_snapshot_id == snapshot_id
    assert closed.actual_value == actual
    assert closed.formula_snapshot  # evidence retained


@pytest.mark.django_db(transaction=True)
def test_close_without_reason_rejected(organization, active_user, grant_action, catalog) -> None:
    metric, rule = _metric_and_rule(active_user, grant_action, catalog)
    period_start, period_end = date(2025, 10, 1), date(2025, 12, 31)
    _seed_ok_aggregate(organization, metric, catalog, period_start, period_end)
    signal = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()[0]
    grant_action(active_user, "risk_signal.close", "risk_signal")
    with pytest.raises(ValidationFailedError):
        CloseRiskSignal(
            context=CommandContext.for_actor(active_user),
            signal_public_id=signal.public_id,
            reason="  ",
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_close_denied_without_scope_or_data_level_does_not_leak(
    organization,
    active_user,
    another_active_user,
    grant_action,
    catalog,
    project: Project,
) -> None:
    metric, rule = _metric_and_rule(active_user, grant_action, catalog)
    period_start, period_end = date(2025, 10, 1), date(2025, 12, 31)
    _seed_ok_aggregate(organization, metric, catalog, period_start, period_end)
    signal = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()[0]

    # Out-of-scope user: no assignment, no grant → deny as not found
    with pytest.raises(PermissionDeniedError) as exc:
        CloseRiskSignal(
            context=CommandContext.for_actor(another_active_user),
            signal_public_id=signal.public_id,
            reason="Nope",
        ).execute()
    assert exc.value.code == "RESOURCE_NOT_FOUND"
    assert "signal" not in exc.value.message.lower() or "not found" in exc.value.message.lower()

    # Same code for unknown id
    with pytest.raises(PermissionDeniedError) as exc2:
        CloseRiskSignal(
            context=CommandContext.for_actor(another_active_user),
            signal_public_id=uuid4(),
            reason="Nope",
        ).execute()
    assert exc2.value.code == exc.value.code
    assert exc2.value.message == exc.value.message

    # Insufficient data level via monitoring assignment
    product = project.product_asset
    assert product is not None
    # Use catalog product: init scope on catalog version needs a project with that product.
    # Assign low data level on catalog product by creating monitoring scope tied to project
    # only when products match; otherwise grant INTERNAL-only is not available via grant_action.
    # Use identity provider path: create scope for catalog via a temporary project link is heavy.
    # Instead: assign supervisor on catalog product through InitializeMonitoringScope on a
    # synthetic setup — re-use project only if same product; else create assignment manually.
    from apps.operations.models import (
        MonitoringAssignment,
        MonitoringAssignmentStatus,
        MonitoringScope,
        MonitoringScopeStatus,
        build_monitoring_scope_key,
    )

    mon_scope = MonitoringScope.objects.create(
        organization=organization,
        project=project,
        product_version=catalog["version"],
        owner=active_user,
        effective_at=timezone.now(),
        status=MonitoringScopeStatus.ACTIVE,
        source_decision_public_id=uuid4(),
    )
    MonitoringAssignment.objects.create(
        organization=organization,
        monitoring_scope=mon_scope,
        supervisor=another_active_user,
        product=catalog["product"],
        sku=catalog["sku"],
        channel=catalog["channel"],
        scope_type=MonitoringScopeType.SKU_CHANNEL,
        scope_key=build_monitoring_scope_key(
            scope_type=MonitoringScopeType.SKU_CHANNEL,
            product_id=catalog["product"].id,
            sku_id=catalog["sku"].id,
            channel_id=catalog["channel"].id,
        ),
        effective_from=timezone.now() - timedelta(days=1),
        status=MonitoringAssignmentStatus.ACTIVE,
        active_slot=1,
        max_data_level=DataSensitivityLevel.INTERNAL,
    )
    with pytest.raises(PermissionDeniedError) as exc3:
        CloseRiskSignal(
            context=CommandContext.for_actor(another_active_user),
            signal_public_id=signal.public_id,
            reason="Still no",
        ).execute()
    assert exc3.value.code == "RESOURCE_NOT_FOUND"
