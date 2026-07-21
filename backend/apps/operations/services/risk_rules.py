"""Governed risk rule drafts, publish, and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    MetricAggregate,
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    MonitoringScopeType,
    OperatingDataSnapshot,
    RiskCoverageStatus,
    RiskRuleStatus,
    RiskRuleVersion,
    RiskSignal,
    RiskSignalStatus,
    build_risk_scope_key,
    validate_risk_parameters,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import SKU, ChannelConfiguration

QUARTER_SHELF_LIFE_MIN_PRODUCTION = "quarter_shelf_life_min_production"

EVALUATOR_REGISTRY: frozenset[str] = frozenset({QUARTER_SHELF_LIFE_MIN_PRODUCTION})


def _authorize_configure(actor) -> None:
    decision = authorize(
        subject_for(actor),
        action="metric_rule.configure",
        resource=ResourceDescriptor(
            resource_type="metric_definition",
            public_id=None,
            organization_id=actor.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _next_version(*, organization_id: int, rule_code: str) -> int:
    latest = (
        RiskRuleVersion.objects.filter(organization_id=organization_id, rule_code=rule_code)
        .order_by("-version_number")
        .first()
    )
    return 1 if latest is None else latest.version_number + 1


@dataclass
class CreateRiskRuleDraft:
    context: CommandContext
    rule_code: str
    name: str
    metric_codes: list[str]
    evaluator_code: str
    parameters_json: dict[str, Any]
    scope_type: str
    valid_from: datetime
    valid_to: datetime | None = None

    def execute(self) -> RiskRuleVersion:
        actor = self.context.actor
        with transaction.atomic():
            _authorize_configure(actor)
            if self.evaluator_code not in EVALUATOR_REGISTRY:
                raise ValidationFailedError(
                    message=f"Unregistered evaluator_code: {self.evaluator_code}"
                )
            if self.scope_type not in MonitoringScopeType.values:
                raise ValidationFailedError(message=f"Unknown scope_type: {self.scope_type}")
            errors = validate_risk_parameters(self.parameters_json)
            if errors:
                raise ValidationFailedError(
                    message="Risk parameters failed validation.",
                    details={"errors": errors},
                )
            return RiskRuleVersion.objects.create(
                organization_id=actor.organization_id,
                rule_code=self.rule_code,
                name=self.name,
                version_number=_next_version(
                    organization_id=actor.organization_id, rule_code=self.rule_code
                ),
                metric_codes=list(self.metric_codes),
                evaluator_code=self.evaluator_code,
                parameters_json=dict(self.parameters_json),
                scope_type=self.scope_type,
                status=RiskRuleStatus.DRAFT,
                valid_from=self.valid_from,
                valid_to=self.valid_to,
                created_by=actor,
            )


@dataclass
class PublishRiskRule:
    context: CommandContext
    rule_public_id: UUID

    def execute(self) -> RiskRuleVersion:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            _authorize_configure(actor)
            rule = (
                RiskRuleVersion.objects.select_for_update()
                .filter(organization_id=actor.organization_id, public_id=self.rule_public_id)
                .first()
            )
            if rule is None:
                raise ValidationFailedError(message="Risk rule not found.")
            if rule.status != RiskRuleStatus.DRAFT:
                raise ValidationFailedError(message="Only DRAFT risk rules can be published.")
            if rule.evaluator_code not in EVALUATOR_REGISTRY:
                raise ValidationFailedError(
                    message=f"Unregistered evaluator_code: {rule.evaluator_code}"
                )
            rule.status = RiskRuleStatus.PUBLISHED
            rule.published_by = actor
            rule.published_at = now
            rule.save(
                update_fields=["status", "published_by", "published_at", "updated_at"]
            )
            return rule


def _evaluate_quarter_shelf(
    *,
    actual: Decimal,
    params: dict[str, Any],
) -> tuple[bool, Decimal, dict[str, Any]]:
    threshold = Decimal(str(params.get("min_production", "0")))
    triggered = actual < threshold
    formula = {
        "evaluator_code": QUARTER_SHELF_LIFE_MIN_PRODUCTION,
        "formula": "actual_production < min_production * target_digestion_ratio",
        "parameters": {
            "min_production": str(params.get("min_production")),
            "shelf_life_days": str(params.get("shelf_life_days")),
            "window_days": str(params.get("window_days")),
            "target_digestion_ratio": str(params.get("target_digestion_ratio")),
        },
    }
    return triggered, threshold, formula


def _create_risk_snapshot(
    *,
    organization_id: int,
    actor,
    sku: SKU,
    channel: ChannelConfiguration,
    metric: MetricDefinitionVersion,
    period_start: date,
    period_end: date,
    period_granularity: str,
    aggregate: MetricAggregate,
) -> OperatingDataSnapshot:
    scope_json = {
        "product_public_ids": [str(sku.product_version.product.public_id)],
        "sku_public_ids": [str(sku.public_id)],
        "channel_public_ids": [str(channel.public_id)],
    }
    periods_json = [
        {
            "period_granularity": period_granularity,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }
    ]
    metric_codes = [metric.metric_code]
    payload_json = {
        "scope": scope_json,
        "periods": periods_json,
        "metric_codes": metric_codes,
        "metrics": [
            {
                "metric_code": metric.metric_code,
                "metric_definition_public_id": str(metric.public_id),
                "metric_version_number": metric.version_number,
                "value": str(aggregate.value) if aggregate.value is not None else None,
                "status": aggregate.status,
                "coverage_rate": str(aggregate.coverage_rate),
                "has_manual_value": aggregate.has_manual_value,
            }
        ],
    }
    snapshot = OperatingDataSnapshot(
        organization_id=organization_id,
        purpose="risk_signal",
        scope_json=scope_json,
        periods_json=periods_json,
        metric_codes=metric_codes,
        payload_json=payload_json,
        created_by=actor,
    )
    snapshot.content_hash = snapshot.compute_content_hash()
    snapshot.save()
    return snapshot


@dataclass
class EvaluateRiskRules:
    rule_version_id: UUID
    period: dict[str, Any]

    def execute(self) -> list[RiskSignal]:
        period_granularity = str(self.period["period_granularity"])
        period_start = self.period["period_start"]
        period_end = self.period["period_end"]
        if isinstance(period_start, str):
            period_start = date.fromisoformat(period_start)
        if isinstance(period_end, str):
            period_end = date.fromisoformat(period_end)

        with transaction.atomic():
            rule = (
                RiskRuleVersion.objects.select_for_update()
                .filter(public_id=self.rule_version_id)
                .first()
            )
            if rule is None or rule.status != RiskRuleStatus.PUBLISHED:
                return []
            if period_end >= date.today():
                return []

            params = dict(rule.parameters_json or {})
            metric_code = str(params.get("metric_code") or (rule.metric_codes or [None])[0] or "")
            metric = (
                MetricDefinitionVersion.objects.filter(
                    organization_id=rule.organization_id,
                    metric_code=metric_code,
                    status=MetricDefinitionStatus.PUBLISHED,
                )
                .order_by("-version_number")
                .first()
            )
            if metric is None:
                return []

            sku_codes = list(params.get("applicable_sku_codes") or [])
            channel_codes = list(params.get("applicable_channel_codes") or [])
            skus = list(
                SKU.objects.filter(
                    organization_id=rule.organization_id, sku_code__in=sku_codes
                ).select_related("product_version__product")
            )
            created: list[RiskSignal] = []
            actor = rule.published_by or rule.created_by
            now = timezone.now()

            for sku in skus:
                channels = ChannelConfiguration.objects.filter(
                    organization_id=rule.organization_id,
                    sku=sku,
                    channel_code__in=channel_codes,
                )
                for channel in channels:
                    aggregate = (
                        MetricAggregate.objects.filter(
                            organization_id=rule.organization_id,
                            grain_type=AggregateGrainType.SKU,
                            grain_id=sku.public_id,
                            channel=channel,
                            metric_definition=metric,
                            period_granularity=period_granularity,
                            period_start=period_start,
                            period_end=period_end,
                        )
                        .order_by("-calculated_at")
                        .first()
                    )
                    if aggregate is None:
                        continue
                    if aggregate.status == AggregateStatus.INSUFFICIENT:
                        continue
                    allowed = {AggregateStatus.OK, AggregateStatus.NOT_COMPARABLE}
                    if aggregate.status not in allowed:
                        min_rate = Decimal(
                            str((metric.coverage_requirement or {}).get("minimum_rate", "0"))
                        )
                        if (
                            aggregate.coverage_rate is not None
                            and aggregate.coverage_rate < min_rate
                        ):
                            continue
                    if aggregate.value is None:
                        continue

                    if rule.evaluator_code == QUARTER_SHELF_LIFE_MIN_PRODUCTION:
                        triggered, threshold, formula = _evaluate_quarter_shelf(
                            actual=aggregate.value, params=params
                        )
                    else:
                        continue
                    if not triggered:
                        continue

                    scope_key = build_risk_scope_key(
                        scope_type=MonitoringScopeType.SKU_CHANNEL,
                        scope_id=str(sku.public_id),
                        channel_id=str(channel.public_id),
                    )
                    existing = RiskSignal.objects.filter(
                        rule_version=rule,
                        scope_key=scope_key,
                        period_start=period_start,
                        period_end=period_end,
                    ).first()
                    if existing is not None:
                        created.append(existing)
                        continue

                    formula["rule_version_number"] = rule.version_number
                    snapshot = _create_risk_snapshot(
                        organization_id=rule.organization_id,
                        actor=actor,
                        sku=sku,
                        channel=channel,
                        metric=metric,
                        period_start=period_start,
                        period_end=period_end,
                        period_granularity=period_granularity,
                        aggregate=aggregate,
                    )
                    try:
                        signal = RiskSignal.objects.create(
                            organization_id=rule.organization_id,
                            rule_version=rule,
                            scope_type=MonitoringScopeType.SKU_CHANNEL,
                            scope_id=sku.public_id,
                            channel=channel,
                            scope_key=scope_key,
                            period_granularity=period_granularity,
                            period_start=period_start,
                            period_end=period_end,
                            status=RiskSignalStatus.NEW,
                            actual_value=aggregate.value,
                            threshold_value=threshold,
                            formula_snapshot=formula,
                            data_snapshot=snapshot,
                            coverage_status=RiskCoverageStatus.SUFFICIENT,
                        )
                    except IntegrityError:
                        signal = RiskSignal.objects.get(
                            rule_version=rule,
                            scope_key=scope_key,
                            period_start=period_start,
                            period_end=period_end,
                        )
                        created.append(signal)
                        continue

                    append_event(
                        AuditRecord(
                            actor=actor,
                            action_code="risk_signal.created",
                            resource_type="risk_signal",
                            resource_public_id=signal.public_id,
                            result=AuditResult.SUCCESS,
                            trace_id=f"evaluate-{signal.public_id}",
                            occurred_at=now,
                            before_summary={},
                            after_summary={"scope_key": scope_key},
                            acting_roles_snapshot=acting_roles_snapshot(actor),
                        )
                    )
                    register_outbox_event(
                        OutboxMessage(
                            event_type="risk_signal.created",
                            aggregate_type="risk_signal",
                            aggregate_id=signal.public_id,
                            payload={
                                "signal_public_id": str(signal.public_id),
                                "organization_id": rule.organization_id,
                                "sku_public_id": str(sku.public_id),
                                "channel_public_id": str(channel.public_id),
                                "product_public_id": str(sku.product_version.product.public_id),
                            },
                            occurred_at=now,
                        )
                    )
                    created.append(signal)
            return created
