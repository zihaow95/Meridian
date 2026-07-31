"""Operating issue permissions stay within monitoring assignment scope."""

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
    MonitoringScopeType,
    OperatingIssueStatus,
)
from apps.operations.services.initialize_monitoring_scope import InitializeMonitoringScope
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.monitoring_assignments import AssignMonitoringSupervisor
from apps.operations.services.operating_issues import CreateOperatingIssue, TransitionOperatingIssue
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.platform.api.errors import PermissionDeniedError
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
        business_no="PRD-ISSUE-PERM",
        name="Perm yogurt",
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
        sku_code="SKU-ISSUE-PERM",
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


def _one_signal(active_user, grant_action, catalog, organization):
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
    return EvaluateRiskRules(
        rule_version_id=rule.public_id,
        period={
            "period_granularity": "QUARTER",
            "period_start": period_start,
            "period_end": period_end,
        },
    ).execute()[0]


@pytest.mark.django_db(transaction=True)
def test_outsider_cannot_create_or_close_issue(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    signal = _one_signal(active_user, grant_action, catalog, organization)
    with pytest.raises(PermissionDeniedError):
        CreateOperatingIssue(
            context=CommandContext.for_actor(another_active_user),
            title="Denied",
            product_public_id=catalog["product"].public_id,
            phenomenon_summary="No rights",
            signal_public_ids=[signal.public_id],
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_assigned_supervisor_can_analyze_in_scope(
    organization,
    active_user,
    another_active_user,
    grant_action,
    catalog,
    project: Project,
) -> None:
    # Align project product with catalog for InitializeMonitoringScope
    project.product_asset = catalog["product"]
    project.save(update_fields=["product_asset", "updated_at"])
    signal = _one_signal(active_user, grant_action, catalog, organization)
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "monitoring_scope.manage", "monitoring_scope")
    issue = CreateOperatingIssue(
        context=CommandContext.for_actor(active_user),
        title="Scoped",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Supervisor review",
        signal_public_ids=[signal.public_id],
    ).execute()
    scope = InitializeMonitoringScope(
        project=project,
        product_version=catalog["version"],
        owner=active_user,
        source_decision_public_id=uuid4(),
        effective_at=timezone.now(),
    ).execute()
    AssignMonitoringSupervisor(
        context=CommandContext.for_actor(active_user),
        monitoring_scope_public_id=scope.public_id,
        supervisor_public_id=another_active_user.public_id,
        scope_type=MonitoringScopeType.PRODUCT,
        product_public_id=catalog["product"].public_id,
    ).execute()
    analyzing = TransitionOperatingIssue(
        context=CommandContext.for_actor(another_active_user),
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    assert analyzing.status == OperatingIssueStatus.ANALYZING
