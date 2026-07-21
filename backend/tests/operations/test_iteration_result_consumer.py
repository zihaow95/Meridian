"""product_version.published writes iteration results back to converted issues."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.consumers import local_consumer_registry
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    OperatingIssueStatus,
)
from apps.operations.services.iteration_proposals import ConvertIssueToIterationProposal
from apps.operations.services.iteration_results import HandleProductVersionPublished
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.operating_issues import CreateOperatingIssue, TransitionOperatingIssue
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
)
from apps.opportunities.models import Opportunity
from apps.platform.application.command import CommandContext
from apps.platform.outbox.consumer import consume_once
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.tasks import merged_consumer_registry
from apps.products.models import (
    SKU,
    ChangeSetStatus,
    ChangeSetType,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)
from apps.projects.models import Project, ProjectOpportunitySource, ProjectType


@pytest.fixture
def catalog(organization: Organization, active_user: User):
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-ITER-RES",
        name="Result yogurt",
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
        sku_code="SKU-ITER-RES",
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


def _converted_issue(active_user, another_active_user, grant_action, catalog, organization):
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    grant_action(active_user, "operating_issue.create", "operating_issue")
    grant_action(active_user, "operating_issue.analyze", "operating_issue")
    grant_action(active_user, "iteration_proposal.convert", "operating_issue")
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
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
        title="Iterate",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Needs iteration",
        signal_public_ids=[signal.public_id],
    ).execute()
    analyzing = TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()
    return ConvertIssueToIterationProposal(
        context=ctx,
        issue_public_id=analyzing.public_id,
        proposal_owner_public_id=another_active_user.public_id,
        idempotency_key="iter-result-1",
        version_no=analyzing.version_no,
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_product_version_published_writes_back_once(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _converted_issue(active_user, another_active_user, grant_action, catalog, organization)
    opportunity = Opportunity.objects.get(public_id=issue.linked_opportunity_id)
    project = Project.objects.create(
        organization=organization,
        business_no="PRJ-ITER-1",
        name="Iteration project",
        project_type=ProjectType.PRODUCT_CHANGE,
        leader=active_user,
        product_asset=catalog["product"],
        idempotency_key=f"prj-{uuid4().hex}",
    )
    ProjectOpportunitySource.objects.create(
        organization=organization,
        project=project,
        opportunity=opportunity,
        source_role="PRIMARY",
        linked_at=timezone.now(),
    )
    published = ProductVersion.objects.create(
        organization=organization,
        product=catalog["product"],
        version_code="V2",
        version_name="Iteration",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
        effective_from=timezone.now(),
    )
    change_set = ProductChangeSet.objects.create(
        organization=organization,
        change_type=ChangeSetType.ITERATION,
        status=ChangeSetStatus.PUBLISHED,
        product=catalog["product"],
        project=project,
        title="Iteration publish",
        published_at=timezone.now(),
        created_by=active_user,
        change_scope={"effective_from": published.effective_from.isoformat()},
    )

    payload = {
        "product_public_id": str(catalog["product"].public_id),
        "product_version_public_id": str(published.public_id),
        "change_set_public_id": str(change_set.public_id),
    }
    first = HandleProductVersionPublished(event_id=uuid4(), payload=payload).execute()
    second = HandleProductVersionPublished(event_id=uuid4(), payload=payload).execute()
    assert first is not None
    assert second is not None
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.linked_project_id == project.public_id
    assert first.linked_product_version_id == published.public_id
    assert first.linked_effective_from is not None
    assert second.linked_product_version_id == first.linked_product_version_id
    assert second.version_no == first.version_no

    event = OutboxEvent.objects.create(
        event_type="product_version.published",
        aggregate_type="product",
        aggregate_id=catalog["product"].public_id,
        payload_json=payload,
        status=OutboxStatus.PENDING,
        occurred_at=timezone.now(),
        next_attempt_at=timezone.now(),
    )
    registry = local_consumer_registry()
    code, handler = registry["product_version.published"]
    assert consume_once(event=event, consumer_code=code, handler=handler) is True
    assert consume_once(event=event, consumer_code=code, handler=handler) is False
    assert "product_version.published" in merged_consumer_registry()
