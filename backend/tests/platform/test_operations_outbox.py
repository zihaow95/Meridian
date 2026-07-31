"""Operations outbox consumers merge with notifications; replay is idempotent."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.notifications.models import Todo
from apps.operations.consumers import local_consumer_registry as operations_registry
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    MonitoringScope,
    MonitoringScopeStatus,
    MonitoringScopeType,
    RiskSignal,
    SignalRecalculation,
    build_monitoring_scope_key,
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
from apps.operations.services.risk_signals import CloseRiskSignal
from apps.platform.application.command import CommandContext
from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus
from apps.platform.outbox.tasks import dispatch_outbox_task
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
        business_no="PRD-OUTBOX-RISK",
        name="Outbox risk yogurt",
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
        sku_code="SKU-OUTBOX-RISK",
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


def _rule_and_signal(organization, active_user, grant_action, catalog, supervisor: User, project):
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    grant_action(active_user, "risk_signal.close", "risk_signal")
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
            source_field_codes=["production_qty"],
            calculation_type="SUM",
            aggregation_rule={"by": ["SKU", "CHANNEL"]},
            window_definition={"granularity": "QUARTER"},
            coverage_requirement={"minimum_rate": "0.8"},
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
        supervisor=supervisor,
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
    )
    signals = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()
    return signals[0], metric, period_start, period_end


@pytest.mark.django_db(transaction=True)
def test_dispatch_merges_operations_and_notifications_registries() -> None:
    from apps.notifications.consumers import local_consumer_registry as notifications_registry
    from apps.platform.outbox.tasks import merged_consumer_registry

    merged = merged_consumer_registry()
    assert "todo.requested" in merged
    assert "risk_signal.created" in merged
    assert "risk_signal.closed" in merged
    assert set(notifications_registry()) <= set(merged)
    assert set(operations_registry()) <= set(merged)


@pytest.mark.django_db(transaction=True)
def test_risk_signal_outbox_consumers_are_idempotent_by_event_id(
    organization, active_user, another_active_user, grant_action, catalog, project: Project
) -> None:
    signal, _metric, _ps, _pe = _rule_and_signal(
        organization, active_user, grant_action, catalog, another_active_user, project
    )
    event = OutboxEvent.objects.filter(
        event_type="risk_signal.created", aggregate_id=signal.public_id
    ).get()
    registry = operations_registry()
    consumer_code, handler = registry["risk_signal.created"][0]
    assert consume_once(event=event, consumer_code=consumer_code, handler=handler) is True
    assert consume_once(event=event, consumer_code=consumer_code, handler=handler) is False
    assert ConsumerReceipt.objects.filter(event=event, consumer_code=consumer_code).count() == 1
    assert (
        Todo.objects.filter(source_id=signal.public_id, assignee=another_active_user).count() == 1
    )


@pytest.mark.django_db(transaction=True)
def test_notification_failure_keeps_signal_and_recalc_replay_without_duplicates(
    organization,
    active_user,
    another_active_user,
    grant_action,
    catalog,
    project: Project,
    monkeypatch,
) -> None:
    signal, metric, period_start, period_end = _rule_and_signal(
        organization, active_user, grant_action, catalog, another_active_user, project
    )
    assert RiskSignal.objects.filter(pk=signal.pk).exists()

    # Simulate consumer/notification failure on first dispatch
    calls = {"n": 0}
    real_registry = operations_registry()

    class BoomHandler:
        def consume(self, event: OutboxEvent) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("redis unavailable")
            real_registry[event.event_type][0][1].consume(event)

    def _failing_merged():
        from apps.notifications.consumers import local_consumer_registry as notifications_registry

        base = {**notifications_registry(), **real_registry}
        code, _ = real_registry["risk_signal.created"][0]
        base["risk_signal.created"] = [(code, BoomHandler())]
        return base

    monkeypatch.setattr(
        "apps.platform.outbox.tasks.merged_consumer_registry",
        _failing_merged,
    )
    created = OutboxEvent.objects.get(
        event_type="risk_signal.created", aggregate_id=signal.public_id
    )
    created.status = OutboxStatus.PENDING
    created.next_attempt_at = timezone.now() - timedelta(seconds=1)
    created.save(update_fields=["status", "next_attempt_at", "updated_at"])

    dispatch_outbox_task(limit=20)
    signal.refresh_from_db()
    assert RiskSignal.objects.filter(pk=signal.pk).exists()
    created.refresh_from_db()
    assert created.status == OutboxStatus.PENDING

    # Recalc still persists in MySQL even if notification path fails later

    # Minimal fact pointing at same scope/period so RecalculateAffectedSignals can resolve
    MetricAggregate.objects.filter(metric_definition=metric).update(value=Decimal("900"))
    # Use signal's own public_id path via fact matching period — create stub fact rows
    # through ORM with required FKs is heavy; call service with signal scope via fact lookup helper.
    # Prefer: create OperatingFact is complex; instead expose optional force via aggregate update
    # and call RecalculateAffectedSignals with a synthetic approach using existing signal scope.
    from apps.operations.services.risk_signals import recalculate_signals_for_scope

    recs = recalculate_signals_for_scope(
        organization_id=organization.id,
        sku_id=catalog["sku"].id,
        channel_id=catalog["channel"].id,
        metric_definition_id=metric.id,
        period_start=period_start,
        period_end=period_end,
        reason="late_aggregate_update",
    )
    assert SignalRecalculation.objects.filter(signal=signal).exists()
    assert len(recs) >= 1

    # Replay succeeds without duplicate todos (backoff must be cleared for immediate retry)
    created.refresh_from_db()
    created.next_attempt_at = timezone.now() - timedelta(seconds=1)
    created.save(update_fields=["next_attempt_at", "updated_at"])
    dispatch_outbox_task(limit=20)
    created.refresh_from_db()
    assert created.status == OutboxStatus.PUBLISHED
    assert (
        Todo.objects.filter(source_id=signal.public_id, assignee=another_active_user).count() == 1
    )

    CloseRiskSignal(
        context=CommandContext.for_actor(active_user),
        signal_public_id=signal.public_id,
        reason="Reviewed after replay",
    ).execute()
    closed = OutboxEvent.objects.get(event_type="risk_signal.closed", aggregate_id=signal.public_id)
    assert closed.status == OutboxStatus.PENDING
    dispatch_outbox_task(limit=20)
    closed.refresh_from_db()
    assert closed.status == OutboxStatus.PUBLISHED
