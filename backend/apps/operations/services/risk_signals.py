"""Risk signal lifecycle and late-data recalculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    ManualEffectiveValue,
    MetricAggregate,
    MetricDefinitionVersion,
    OperatingFact,
    RiskSignal,
    RiskSignalStatus,
    SignalRecalculation,
)
from apps.operations.policies.identity_provider import resolve_effective_assignments
from apps.operations.services.risk_rules import (
    QUARTER_SHELF_LIFE_MIN_PRODUCTION,
    _evaluate_quarter_shelf,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import SKU, ChannelConfiguration


def _not_found() -> PermissionDeniedError:
    return PermissionDeniedError()


def _signal_or_deny(*, organization_id: int, signal_public_id: UUID) -> RiskSignal:
    signal = (
        RiskSignal.objects.select_related("channel", "rule_version", "data_snapshot")
        .filter(organization_id=organization_id, public_id=signal_public_id)
        .first()
    )
    if signal is None:
        raise _not_found()
    return signal


def _authorize_signal_action(
    *,
    actor,
    action: str,
    signal: RiskSignal,
) -> None:
    sku = SKU.objects.filter(public_id=signal.scope_id).select_related(
        "product_version__product"
    ).first()
    channel = signal.channel
    product = sku.product_version.product if sku is not None else None
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="risk_signal",
            public_id=signal.public_id,
            organization_id=actor.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={
                "product_public_id": str(product.public_id) if product else None,
                "sku_public_id": str(sku.public_id) if sku else None,
                "channel_public_id": str(channel.public_id) if channel else None,
            },
        ),
        context=AuthorizationContext.current(),
    )
    if decision.allowed:
        return

    # Fallback: monitoring assignment with sufficient data level
    assignments = resolve_effective_assignments(
        user=actor, organization_id=actor.organization_id
    )
    required = DataSensitivityLevel.SENSITIVE_CONTROLLED
    for assignment in assignments:
        if product is None:
            continue
        if assignment.product_id != product.id:
            continue
        if sku is not None and assignment.sku_id and assignment.sku_id != sku.id:
            continue
        if channel is not None and assignment.channel_id and assignment.channel_id != channel.id:
            continue
        if LEVEL_RANK.get(assignment.max_data_level, 0) < LEVEL_RANK.get(required, 0):
            continue
        return
    raise _not_found()


@dataclass
class MarkRiskSignalViewed:
    context: CommandContext
    signal_public_id: UUID

    def execute(self) -> RiskSignal:
        actor = self.context.actor
        with transaction.atomic():
            signal = _signal_or_deny(
                organization_id=actor.organization_id, signal_public_id=self.signal_public_id
            )
            _authorize_signal_action(actor=actor, action="risk_signal.read", signal=signal)
            if signal.status == RiskSignalStatus.NEW:
                signal.status = RiskSignalStatus.VIEWED
                signal.save(update_fields=["status", "updated_at"])
            return signal


@dataclass
class CloseRiskSignal:
    context: CommandContext
    signal_public_id: UUID
    reason: str

    def execute(self) -> RiskSignal:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        reason = (self.reason or "").strip()
        if not reason:
            raise ValidationFailedError(message="Close reason is required.")
        with transaction.atomic():
            signal = _signal_or_deny(
                organization_id=actor.organization_id, signal_public_id=self.signal_public_id
            )
            _authorize_signal_action(actor=actor, action="risk_signal.close", signal=signal)
            if signal.status == RiskSignalStatus.CLOSED:
                return signal
            if signal.status not in {RiskSignalStatus.NEW, RiskSignalStatus.VIEWED}:
                raise ValidationFailedError(message="Signal cannot be closed from current status.")
            signal.status = RiskSignalStatus.CLOSED
            signal.closed_reason = reason
            signal.closed_by = actor
            signal.closed_at = now
            signal.save(
                update_fields=[
                    "status",
                    "closed_reason",
                    "closed_by",
                    "closed_at",
                    "updated_at",
                ]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="risk_signal.close",
                    resource_type="risk_signal",
                    resource_public_id=signal.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={"reason": reason},
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="risk_signal.closed",
                    aggregate_type="risk_signal",
                    aggregate_id=signal.public_id,
                    payload={
                        "signal_public_id": str(signal.public_id),
                        "organization_id": signal.organization_id,
                        "reason": reason,
                    },
                    occurred_at=now,
                )
            )
            return signal


def _current_aggregate_value(
    *,
    organization_id: int,
    sku: SKU,
    channel: ChannelConfiguration,
    metric: MetricDefinitionVersion,
    period_start: date,
    period_end: date,
    period_granularity: str,
) -> Decimal | None:
    aggregate = (
        MetricAggregate.objects.filter(
            organization_id=organization_id,
            grain_type=AggregateGrainType.SKU,
            grain_id=sku.public_id,
            channel=channel,
            metric_definition=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            status=AggregateStatus.OK,
        )
        .order_by("-calculated_at")
        .first()
    )
    return aggregate.value if aggregate is not None else None


def recalculate_signals_for_scope(
    *,
    organization_id: int,
    sku_id: int,
    channel_id: int,
    metric_definition_id: int,
    period_start: date,
    period_end: date,
    reason: str,
    triggered_by_fact: OperatingFact | None = None,
    triggered_by_manual: ManualEffectiveValue | None = None,
) -> list[SignalRecalculation]:
    with transaction.atomic():
        sku = SKU.objects.filter(pk=sku_id).first()
        channel = ChannelConfiguration.objects.filter(pk=channel_id).first()
        metric = MetricDefinitionVersion.objects.filter(pk=metric_definition_id).first()
        if sku is None or channel is None or metric is None:
            return []

        signals = list(
            RiskSignal.objects.select_related("rule_version")
            .filter(
                organization_id=organization_id,
                scope_id=sku.public_id,
                channel=channel,
                period_start=period_start,
                period_end=period_end,
            )
            .select_for_update()
        )
        new_value = _current_aggregate_value(
            organization_id=organization_id,
            sku=sku,
            channel=channel,
            metric=metric,
            period_start=period_start,
            period_end=period_end,
            period_granularity=signals[0].period_granularity if signals else "QUARTER",
        )
        if new_value is None:
            return []

        recs: list[SignalRecalculation] = []
        now = timezone.now()
        for signal in signals:
            rule = signal.rule_version
            params = dict(rule.parameters_json or {})
            if rule.evaluator_code == QUARTER_SHELF_LIFE_MIN_PRODUCTION:
                _triggered, new_threshold, _formula = _evaluate_quarter_shelf(
                    actual=new_value, params=params
                )
            else:
                new_threshold = signal.threshold_value
            old_actual = signal.actual_value
            old_threshold = signal.threshold_value
            # Historical signal snapshot values are immutable.
            signal.display_recalculated_at = now
            signal.save(update_fields=["display_recalculated_at", "updated_at"])
            rec = SignalRecalculation.objects.create(
                organization_id=organization_id,
                signal=signal,
                reason=reason,
                old_actual_value=old_actual,
                new_actual_value=new_value,
                old_threshold_value=old_threshold,
                new_threshold_value=new_threshold,
                impact_summary=(
                    f"Display value recalculated from {old_actual} to {new_value}; "
                    "historical signal evidence retained."
                ),
                triggered_by_fact=triggered_by_fact,
                triggered_by_manual=triggered_by_manual,
                calculated_at=now,
            )
            recs.append(rec)
        return recs


@dataclass
class RecalculateAffectedSignals:
    fact_public_id: UUID | None = None
    manual_value_public_id: UUID | None = None

    def execute(self) -> list[SignalRecalculation]:
        with transaction.atomic():
            if self.fact_public_id is not None:
                fact = (
                    OperatingFact.objects.select_related("sku", "channel", "metric_definition")
                    .filter(public_id=self.fact_public_id)
                    .first()
                )
                if fact is None:
                    return []
                return recalculate_signals_for_scope(
                    organization_id=fact.organization_id,
                    sku_id=fact.sku_id,
                    channel_id=fact.channel_id,
                    metric_definition_id=fact.metric_definition_id,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    reason="late_fact",
                    triggered_by_fact=fact,
                )
            if self.manual_value_public_id is not None:
                manual = (
                    ManualEffectiveValue.objects.select_related(
                        "sku", "channel", "metric_definition"
                    )
                    .filter(public_id=self.manual_value_public_id)
                    .first()
                )
                if manual is None:
                    return []
                return recalculate_signals_for_scope(
                    organization_id=manual.organization_id,
                    sku_id=manual.sku_id,
                    channel_id=manual.channel_id,
                    metric_definition_id=manual.metric_definition_id,
                    period_start=manual.period_start,
                    period_end=manual.period_end,
                    reason="manual_effective_value",
                    triggered_by_manual=manual,
                )
            return []
