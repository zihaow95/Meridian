"""Operating issue workflow: multi-signal links, transitions, and decisions."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.errors import IssueImmutableState, IssueVersionConflict
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    IssueSignal,
    IssueSourceType,
    MetricAggregate,
    OperatingIssue,
    OperatingIssueStatus,
    RecommendationType,
    RiskSignalStatus,
)
from apps.operations.queries.operating_issues import get_operating_issue
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.operating_issues import (
    CreateOperatingIssue,
    EscalateRiskSignal,
    RecordOperatingIssueDecision,
    TransitionOperatingIssue,
)
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.platform.api.errors import ValidationFailedError
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
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-ISSUE",
        name="Issue yogurt",
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
        sku_code="SKU-ISSUE",
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


def _signals(active_user, grant_action, catalog, organization, count: int = 2):
    grant_action(active_user, "metric_rule.configure", "metric_definition")
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
    created = []
    for index in range(count):
        period_start = date(2025, 1 + index * 3, 1)
        period_end = date(2025, 3 + index * 3, 28 if index == 0 else 30)
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
        signals = EvaluateRiskRules(
            rule_version_id=rule.public_id,
            period={
                "period_granularity": "QUARTER",
                "period_start": period_start,
                "period_end": period_end,
            },
        ).execute()
        created.extend(signals)
    return created


@pytest.mark.django_db(transaction=True)
def test_issue_links_multiple_signals_and_one_active_primary(
    organization, active_user, grant_action, catalog
) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=2)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    issue = CreateOperatingIssue(
        context=CommandContext.for_actor(active_user),
        title="Low production",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Two quarters below threshold",
        signal_public_ids=[signals[0].public_id, signals[1].public_id],
    ).execute()
    links = list(IssueSignal.objects.filter(issue=issue).order_by("id"))
    assert len(links) == 2
    primaries = [link for link in links if link.active_primary_slot == 1]
    assert len(primaries) == 1
    assert primaries[0].signal_id == signals[0].id
    for signal in signals:
        signal.refresh_from_db()
        assert signal.status == RiskSignalStatus.ESCALATED
    assert issue.data_snapshot_id is not None
    assert OutboxEvent.objects.filter(
        event_type="operating_issue.created", aggregate_id=issue.public_id
    ).exists()
    payload = get_operating_issue(organization_id=organization.id, issue_public_id=issue.public_id)
    assert len(payload["signals"]) == 2


@pytest.mark.django_db(transaction=True)
def test_signal_cannot_have_two_active_primary_issues(
    organization, active_user, grant_action, catalog
) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=1)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    ctx = CommandContext.for_actor(active_user)
    CreateOperatingIssue(
        context=ctx,
        title="First",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="First issue",
        signal_public_ids=[signals[0].public_id],
    ).execute()
    with pytest.raises(ValidationFailedError):
        CreateOperatingIssue(
            context=ctx,
            title="Second",
            product_public_id=catalog["product"].public_id,
            phenomenon_summary="Second issue",
            signal_public_ids=[signals[0].public_id],
        ).execute()
    assert IssueSignal.objects.filter(signal=signals[0], active_primary_slot=1).count() == 1


@pytest.mark.django_db(transaction=True)
def test_status_transitions_and_immutable_converted_state(
    organization, active_user, grant_action, catalog
) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=1)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "operating_issue.analyze", "operating_issue")
    grant_action(active_user, "operating_issue.close", "operating_issue")
    ctx = CommandContext.for_actor(active_user)
    issue = CreateOperatingIssue(
        context=ctx,
        title="Transition",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Need analysis",
        signal_public_ids=[signals[0].public_id],
    ).execute()
    analyzing = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    observing = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=analyzing.public_id,
        version_no=analyzing.version_no,
        target_status=OperatingIssueStatus.OBSERVING,
    ).execute()
    back = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=observing.public_id,
        version_no=observing.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    converted = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=back.public_id,
        version_no=back.version_no,
        target_status=OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
    ).execute()
    assert converted.status == OperatingIssueStatus.CONVERTED_TO_PROPOSAL
    with pytest.raises(IssueImmutableState):
        TransitionOperatingIssue(
            context=ctx,
            issue_public_id=converted.public_id,
            version_no=converted.version_no,
            target_status=OperatingIssueStatus.CLOSED,
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_direct_source_requires_materials_and_keeps_snapshot(
    organization, active_user, grant_action, catalog
) -> None:
    grant_action(active_user, "operating_issue.create", "operating_issue")
    ctx = CommandContext.for_actor(active_user)
    with pytest.raises(ValidationFailedError):
        CreateOperatingIssue(
            context=ctx,
            title="Portfolio",
            product_public_id=catalog["product"].public_id,
            phenomenon_summary="Quarterly review",
            source_type=IssueSourceType.PRODUCT_PORTFOLIO_REVIEW,
            source_materials_json={},
        ).execute()
    issue = CreateOperatingIssue(
        context=ctx,
        title="Portfolio",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Quarterly review",
        source_type=IssueSourceType.PRODUCT_PORTFOLIO_REVIEW,
        source_materials_json={"deck_version": "v3", "meeting": "Q4"},
    ).execute()
    assert issue.source_type == IssueSourceType.PRODUCT_PORTFOLIO_REVIEW
    assert issue.data_snapshot_id is not None
    assert IssueSignal.objects.filter(issue=issue).count() == 0


@pytest.mark.django_db(transaction=True)
def test_decision_appends_and_stale_version_conflicts(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=1)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "operating_issue.analyze", "operating_issue")
    ctx = CommandContext.for_actor(active_user)
    issue = CreateOperatingIssue(
        context=ctx,
        title="Decide",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Need light action",
        signal_public_ids=[signals[0].public_id],
    ).execute()
    TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    issue.refresh_from_db()
    decision = RecordOperatingIssueDecision(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        recommendation_type=RecommendationType.ADJUST_CHANNEL,
        action_summary="Shift spend to Douyin",
        responsible_user_public_id=another_active_user.public_id,
        planned_at=timezone.now() + timedelta(days=7),
    ).execute()
    issue.refresh_from_db()
    assert issue.status == OperatingIssueStatus.ACTIONING
    assert issue.recommendation_type == RecommendationType.ADJUST_CHANNEL
    assert decision.action_summary == "Shift spend to Douyin"
    assert OutboxEvent.objects.filter(event_type="operating_issue.decided").exists()
    with pytest.raises(IssueVersionConflict):
        RecordOperatingIssueDecision(
            context=ctx,
            issue_public_id=issue.public_id,
            version_no=1,
            recommendation_type=RecommendationType.CLOSE,
            action_summary="stale",
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_close_clears_active_primary_slot_not_history(
    organization, active_user, grant_action, catalog
) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=1)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "operating_issue.analyze", "operating_issue")
    grant_action(active_user, "operating_issue.close", "operating_issue")
    ctx = CommandContext.for_actor(active_user)
    issue = CreateOperatingIssue(
        context=ctx,
        title="Close me",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Transient",
        signal_public_ids=[signals[0].public_id],
    ).execute()
    analyzing = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    closed = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=analyzing.public_id,
        version_no=analyzing.version_no,
        target_status=OperatingIssueStatus.CLOSED,
    ).execute()
    link = IssueSignal.objects.get(issue=closed, signal=signals[0])
    assert link.active_primary_slot is None
    assert link.unlinked_at is not None
    assert IssueSignal.objects.filter(issue=closed).count() == 1


@pytest.mark.django_db(transaction=True)
def test_escalate_creates_issue(organization, active_user, grant_action, catalog) -> None:
    signals = _signals(active_user, grant_action, catalog, organization, count=1)
    grant_action(active_user, "risk_signal.escalate", "risk_signal")
    grant_action(active_user, "operating_issue.create", "operating_issue")
    issue = EscalateRiskSignal(
        context=CommandContext.for_actor(active_user),
        signal_public_id=signals[0].public_id,
        title="Escalated",
        phenomenon_summary="Needs business review",
    ).execute()
    assert isinstance(issue, OperatingIssue)
    assert IssueSignal.objects.filter(
        issue=issue, signal=signals[0], active_primary_slot=1
    ).exists()
