"""Concurrent escalate/create keeps a single active primary issue per signal."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment, ScopeType
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.operations.errors import OperatingIssueAlreadyLinked
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    IssueSignal,
    MetricAggregate,
    OperatingIssue,
)
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.operations.services.operating_issues import CreateOperatingIssue
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    CreateRiskRuleDraft,
    EvaluateRiskRules,
    PublishRiskRule,
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


def _grant(user: User, action_code: str, resource_type: str) -> None:
    action, _ = PermissionAction.objects.get_or_create(
        action_code=action_code,
        defaults={"resource_type": resource_type, "action_category": ActionCategory.ADMIN},
    )
    role, _ = Role.objects.get_or_create(
        role_code=f"ROLE_{action_code.replace('.', '_').upper()}_CONC",
        defaults={"name": action_code, "role_type": RoleType.PLATFORM},
    )
    RolePermission.objects.get_or_create(
        role=role,
        action=action,
        defaults={
            "max_data_level": DataSensitivityLevel.HIGHLY_SENSITIVE,
            "requires_object_scope": False,
        },
    )
    RoleAssignment.objects.get_or_create(
        user=user,
        role=role,
        defaults={
            "scope_type": ScopeType.ORGANIZATION,
            "effective_from": timezone.now(),
            "configured_by": user,
        },
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_primary_link_only_one_wins() -> None:
    organization = Organization.objects.create(name="Issue Conc Org")
    user = User.objects.create_user(
        organization=organization,
        display_name="Conc User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    _grant(user, "metric_rule.configure", "metric_definition")
    _grant(user, "operating_issue.create", "operating_issue")
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-CONC-ISSUE",
        name="Conc",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=user,
    )
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=user,
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-CONC-ISSUE",
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
    ctx = CommandContext.for_actor(user)
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
                "applicable_sku_codes": [sku.sku_code],
                "applicable_channel_codes": [channel.channel_code],
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
        grain_id=sku.public_id,
        channel=channel,
        channel_key=str(channel.public_id),
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

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    created: list[OperatingIssue] = []
    lock = threading.Lock()

    def _run(title: str) -> None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            issue = CreateOperatingIssue(
                context=CommandContext.for_actor(user),
                title=title,
                product_public_id=product.public_id,
                phenomenon_summary=title,
                signal_public_ids=[signal.public_id],
            ).execute()
            with lock:
                created.append(issue)
        except BaseException as exc:  # noqa: BLE001 - collect either outcome
            with lock:
                errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_run, args=("Issue-0",))
    t2 = threading.Thread(target=_run, args=("Issue-1",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(created) == 1, (created, errors)
    assert len(errors) == 1, errors
    assert isinstance(errors[0], OperatingIssueAlreadyLinked)
    assert IssueSignal.objects.filter(signal=signal, active_primary_slot=1).count() == 1
    assert OperatingIssue.objects.filter(organization=organization).count() == 1
