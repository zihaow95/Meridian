"""Operating issue outbox consumers create owner/action todos idempotently."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.notifications.models import Todo
from apps.operations.consumers import local_consumer_registry
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    OperatingIssueStatus,
    RecommendationType,
)
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.operating_issues import (
    CreateOperatingIssue,
    RecordOperatingIssueDecision,
    TransitionOperatingIssue,
)
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.platform.application.command import CommandContext
from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.models import OutboxEvent
from apps.platform.outbox.tasks import merged_consumer_registry
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
        business_no="PRD-ISSUE-TODO",
        name="Todo yogurt",
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
        sku_code="SKU-ISSUE-TODO",
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


@pytest.mark.django_db(transaction=True)
def test_issue_created_and_decided_todos_are_idempotent(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "operating_issue.analyze", "operating_issue")
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
    signal = EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()[0]
    issue = CreateOperatingIssue(
        context=ctx,
        title="Todo issue",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Needs owner todo",
        signal_public_ids=[signal.public_id],
    ).execute()
    created_event = OutboxEvent.objects.get(
        event_type="operating_issue.created", aggregate_id=issue.public_id
    )
    registry = local_consumer_registry()
    code, handler = registry["operating_issue.created"]
    assert consume_once(event=created_event, consumer_code=code, handler=handler) is True
    assert consume_once(event=created_event, consumer_code=code, handler=handler) is False
    assert Todo.objects.filter(source_id=issue.public_id, assignee=active_user).count() == 1

    TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    issue.refresh_from_db()
    RecordOperatingIssueDecision(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        recommendation_type=RecommendationType.ADJUST_MARKET,
        action_summary="Campaign boost",
        responsible_user_public_id=another_active_user.public_id,
    ).execute()
    decided_event = OutboxEvent.objects.filter(event_type="operating_issue.decided").latest(
        "created_at"
    )
    d_code, d_handler = registry["operating_issue.decided"]
    assert consume_once(event=decided_event, consumer_code=d_code, handler=d_handler) is True
    assert consume_once(event=decided_event, consumer_code=d_code, handler=d_handler) is False
    assert (
        Todo.objects.filter(source_id=issue.public_id, assignee=another_active_user).count() == 1
    )
    merged = merged_consumer_registry()
    assert "operating_issue.created" in merged
    assert "operating_issue.decided" in merged
