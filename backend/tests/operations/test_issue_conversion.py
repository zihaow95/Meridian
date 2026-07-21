"""Convert operating issues into DRAFT iteration opportunities."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.operations.errors import IssueImmutableState
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    IssueConversion,
    IssueConversionType,
    MetricAggregate,
    OperatingIssueStatus,
)
from apps.operations.services.iteration_proposals import ConvertIssueToIterationProposal
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
from apps.opportunities.errors import ProposalOwnerNotEligible
from apps.opportunities.models import InitialType, Opportunity, ProposalStatus
from apps.platform.api.errors import PermissionDeniedError
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
        business_no="PRD-CONV",
        name="Conv yogurt",
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
        sku_code="SKU-CONV",
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


def _ready_issue(active_user, grant_action, catalog, organization):
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
        title="Low production",
        product_public_id=catalog["product"].public_id,
        phenomenon_summary="Below shelf-life digestion threshold",
        signal_public_ids=[signal.public_id],
    ).execute()
    return TransitionOperatingIssue(
        context=ctx,
        issue_public_id=issue.public_id,
        version_no=issue.version_no,
        target_status=OperatingIssueStatus.ANALYZING,
    ).execute()


@pytest.mark.django_db(transaction=True)
def test_convert_creates_iteration_draft_and_links_without_submit(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _ready_issue(active_user, grant_action, catalog, organization)
    grant_action(active_user, "iteration_proposal.convert", "operating_issue")
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    converted = ConvertIssueToIterationProposal(
        context=CommandContext.for_actor(active_user),
        issue_public_id=issue.public_id,
        proposal_owner_public_id=another_active_user.public_id,
        idempotency_key="conv-1",
        version_no=issue.version_no,
    ).execute()
    assert converted.status == OperatingIssueStatus.CONVERTED_TO_PROPOSAL
    assert converted.linked_opportunity_id is not None
    opportunity = Opportunity.objects.get(public_id=converted.linked_opportunity_id)
    assert opportunity.initial_type == InitialType.ITERATION
    assert opportunity.proposal_status == ProposalStatus.DRAFT
    assert opportunity.proposal_owner_id == another_active_user.id
    snapshot = opportunity.current_version.content_snapshot
    assert snapshot["product_public_id"] == str(catalog["product"].public_id)
    assert snapshot["phenomenon_summary"]
    assert snapshot["signals"]
    assert IssueConversion.objects.filter(
        issue=converted, conversion_type=IssueConversionType.ITERATION_PROPOSAL
    ).count() == 1
    assert OutboxEvent.objects.filter(event_type="operating_issue.converted").count() == 1
    assert AuditEvent.objects.filter(action_code="iteration_proposal.convert").count() == 1


@pytest.mark.django_db(transaction=True)
def test_convert_rejects_ineligible_proposal_owner(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _ready_issue(active_user, grant_action, catalog, organization)
    grant_action(active_user, "iteration_proposal.convert", "operating_issue")
    with pytest.raises(ProposalOwnerNotEligible):
        ConvertIssueToIterationProposal(
            context=CommandContext.for_actor(active_user),
            issue_public_id=issue.public_id,
            proposal_owner_public_id=another_active_user.public_id,
            idempotency_key="conv-ineligible",
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_convert_idempotent_by_key_and_blocks_second_conversion(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _ready_issue(active_user, grant_action, catalog, organization)
    grant_action(active_user, "iteration_proposal.convert", "operating_issue")
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    ctx = CommandContext.for_actor(active_user)
    first = ConvertIssueToIterationProposal(
        context=ctx,
        issue_public_id=issue.public_id,
        proposal_owner_public_id=another_active_user.public_id,
        idempotency_key="same-key",
    ).execute()
    again = ConvertIssueToIterationProposal(
        context=ctx,
        issue_public_id=issue.public_id,
        proposal_owner_public_id=another_active_user.public_id,
        idempotency_key="same-key",
    ).execute()
    assert again.public_id == first.public_id
    assert Opportunity.objects.count() == 1
    with pytest.raises(IssueImmutableState):
        ConvertIssueToIterationProposal(
            context=ctx,
            issue_public_id=issue.public_id,
            proposal_owner_public_id=another_active_user.public_id,
            idempotency_key="other-key",
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_concurrent_convert_creates_one_opportunity(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _ready_issue(active_user, grant_action, catalog, organization)
    grant_action(active_user, "iteration_proposal.convert", "operating_issue")
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []
    lock = threading.Lock()

    def _run(key: str) -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            issue_row = ConvertIssueToIterationProposal(
                context=CommandContext.for_actor(active_user),
                issue_public_id=issue.public_id,
                proposal_owner_public_id=another_active_user.public_id,
                idempotency_key=key,
            ).execute()
            with lock:
                results.append(issue_row)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_run, args=("c-a",))
    t2 = threading.Thread(target=_run, args=("c-b",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert len(results) == 1, (results, errors)
    assert len(errors) == 1, errors
    assert Opportunity.objects.count() == 1
    assert IssueConversion.objects.count() == 1
    assert OutboxEvent.objects.filter(event_type="operating_issue.converted").count() == 1


@pytest.mark.django_db(transaction=True)
def test_convert_denied_without_permission(
    organization, active_user, another_active_user, grant_action, catalog
) -> None:
    issue = _ready_issue(active_user, grant_action, catalog, organization)
    grant_action(another_active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    with pytest.raises(PermissionDeniedError):
        ConvertIssueToIterationProposal(
            context=CommandContext.for_actor(active_user),
            issue_public_id=issue.public_id,
            proposal_owner_public_id=another_active_user.public_id,
            idempotency_key="denied",
        ).execute()
