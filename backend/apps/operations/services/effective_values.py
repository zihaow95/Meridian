"""Manual effective values and effective-value resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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
    ManualEffectiveValue,
    ManualEffectiveValueStatus,
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    OperatingFact,
    OperatingFactStatus,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import SKU, ChannelConfiguration


@dataclass
class EffectiveValueResult:
    is_manual: bool
    numeric_value: Decimal | None
    coverage_status: str
    fact_status: str | None = None
    manual_value_public_id: UUID | None = None
    fact_public_id: UUID | None = None


def _authorize(actor, action: str, *, public_id: UUID | None = None) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="operating_value",
            public_id=public_id,
            organization_id=actor.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _get_sku_channel(organization_id: int, sku_public_id: UUID, channel_public_id: UUID):
    sku = SKU.objects.filter(organization_id=organization_id, public_id=sku_public_id).first()
    channel = ChannelConfiguration.objects.filter(
        organization_id=organization_id, public_id=channel_public_id
    ).first()
    if sku is None or channel is None or channel.sku_id != sku.id:
        raise ValidationFailedError(message="SKU/channel not found.")
    return sku, channel


def _current_source_fact(
    *,
    organization_id: int,
    sku_id: int,
    channel_id: int,
    metric: MetricDefinitionVersion,
    period_start: date,
    period_end: date,
    period_granularity: str,
) -> OperatingFact | None:
    facts = list(
        OperatingFact.objects.filter(
            organization_id=organization_id,
            sku_id=sku_id,
            channel_id=channel_id,
            metric_definition=metric,
            period_start=period_start,
            period_end=period_end,
            period_granularity=period_granularity,
            fact_status=OperatingFactStatus.VALID,
            active_slot=1,
        ).select_related("source", "source__configuration_version")
    )
    if not facts:
        return None

    def _sort_key(fact: OperatingFact) -> tuple[int, datetime]:
        return (fact.source.locked_source_priority(), fact.source_timestamp)

    return sorted(facts, key=_sort_key, reverse=True)[0]


@dataclass
class ResolveEffectiveOperatingValue:
    context: CommandContext
    sku_public_id: UUID
    channel_public_id: UUID
    metric_code: str
    period_start: date
    period_end: date
    period_granularity: str

    def execute(self) -> EffectiveValueResult:
        actor = self.context.actor
        sku, channel = _get_sku_channel(
            actor.organization_id, self.sku_public_id, self.channel_public_id
        )
        metric = (
            MetricDefinitionVersion.objects.filter(
                organization_id=actor.organization_id,
                metric_code=self.metric_code,
                status=MetricDefinitionStatus.PUBLISHED,
            )
            .order_by("-version_number")
            .first()
        )
        if metric is None:
            return EffectiveValueResult(
                is_manual=False,
                numeric_value=None,
                coverage_status="INSUFFICIENT",
            )

        manual = ManualEffectiveValue.objects.filter(
            organization_id=actor.organization_id,
            sku=sku,
            channel=channel,
            metric_definition=metric,
            period_start=self.period_start,
            period_end=self.period_end,
            period_granularity=self.period_granularity,
            status=ManualEffectiveValueStatus.ACTIVE,
            active_slot=1,
        ).first()
        if manual is not None:
            return EffectiveValueResult(
                is_manual=True,
                numeric_value=manual.numeric_value,
                coverage_status="SUFFICIENT",
                manual_value_public_id=manual.public_id,
            )

        fact = _current_source_fact(
            organization_id=actor.organization_id,
            sku_id=sku.id,
            channel_id=channel.id,
            metric=metric,
            period_start=self.period_start,
            period_end=self.period_end,
            period_granularity=self.period_granularity,
        )
        if fact is None:
            return EffectiveValueResult(
                is_manual=False,
                numeric_value=None,
                coverage_status="INSUFFICIENT",
            )
        return EffectiveValueResult(
            is_manual=False,
            numeric_value=fact.numeric_value,
            coverage_status="SUFFICIENT",
            fact_status=fact.fact_status,
            fact_public_id=fact.public_id,
        )


@dataclass
class CreateManualEffectiveValue:
    context: CommandContext
    sku_public_id: UUID
    channel_public_id: UUID
    metric_definition_public_id: UUID
    period_granularity: str
    period_start: date
    period_end: date
    numeric_value: Decimal
    reason: str
    text_value: str = ""

    def execute(self) -> ManualEffectiveValue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            _authorize(actor, "manual_effective_value.create")
            sku, channel = _get_sku_channel(
                actor.organization_id, self.sku_public_id, self.channel_public_id
            )
            metric = MetricDefinitionVersion.objects.filter(
                organization_id=actor.organization_id,
                public_id=self.metric_definition_public_id,
                status=MetricDefinitionStatus.PUBLISHED,
            ).first()
            if metric is None:
                raise ValidationFailedError(message="Metric definition not found.")
            original = _current_source_fact(
                organization_id=actor.organization_id,
                sku_id=sku.id,
                channel_id=channel.id,
                metric=metric,
                period_start=self.period_start,
                period_end=self.period_end,
                period_granularity=self.period_granularity,
            )
            try:
                manual = ManualEffectiveValue.objects.create(
                    organization_id=actor.organization_id,
                    sku=sku,
                    channel=channel,
                    metric_definition=metric,
                    period_granularity=self.period_granularity,
                    period_start=self.period_start,
                    period_end=self.period_end,
                    original_fact=original,
                    numeric_value=self.numeric_value,
                    text_value=self.text_value,
                    reason=self.reason,
                    valid_from=now,
                    status=ManualEffectiveValueStatus.ACTIVE,
                    active_slot=1,
                    confirmed_by=actor,
                    confirmed_at=now,
                )
            except IntegrityError:
                raise
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="manual_effective_value.create",
                    resource_type="operating_value",
                    resource_public_id=manual.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={"numeric_value": str(self.numeric_value)},
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="operating_value.overridden",
                    aggregate_type="manual_effective_value",
                    aggregate_id=manual.public_id,
                    payload={"manual_value_public_id": str(manual.public_id)},
                    occurred_at=now,
                )
            )
            return manual


@dataclass
class ModifyManualEffectiveValue:
    context: CommandContext
    manual_value_public_id: UUID
    numeric_value: Decimal
    reason: str
    text_value: str = ""

    def execute(self) -> ManualEffectiveValue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            _authorize(
                actor,
                "manual_effective_value.modify",
                public_id=self.manual_value_public_id,
            )
            current = (
                ManualEffectiveValue.objects.select_for_update()
                .filter(
                    organization_id=actor.organization_id,
                    public_id=self.manual_value_public_id,
                    status=ManualEffectiveValueStatus.ACTIVE,
                    active_slot=1,
                )
                .first()
            )
            if current is None:
                raise ValidationFailedError(message="Active manual value not found.")
            current.status = ManualEffectiveValueStatus.SUPERSEDED
            current.active_slot = None
            current.valid_to = now
            current.save(update_fields=["status", "active_slot", "valid_to", "updated_at"])
            replacement = ManualEffectiveValue.objects.create(
                organization_id=actor.organization_id,
                sku=current.sku,
                channel=current.channel,
                metric_definition=current.metric_definition,
                period_granularity=current.period_granularity,
                period_start=current.period_start,
                period_end=current.period_end,
                original_fact=current.original_fact,
                numeric_value=self.numeric_value,
                text_value=self.text_value or current.text_value,
                reason=self.reason,
                valid_from=now,
                status=ManualEffectiveValueStatus.ACTIVE,
                active_slot=1,
                confirmed_by=actor,
                confirmed_at=now,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="manual_effective_value.modify",
                    resource_type="operating_value",
                    resource_public_id=replacement.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={"previous_public_id": str(current.public_id)},
                    after_summary={"numeric_value": str(self.numeric_value)},
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="operating_value.overridden",
                    aggregate_type="manual_effective_value",
                    aggregate_id=replacement.public_id,
                    payload={"manual_value_public_id": str(replacement.public_id)},
                    occurred_at=now,
                )
            )
            return replacement


@dataclass
class RevokeManualEffectiveValue:
    context: CommandContext
    manual_value_public_id: UUID
    reason: str

    def execute(self) -> ManualEffectiveValue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            _authorize(
                actor,
                "manual_effective_value.revoke",
                public_id=self.manual_value_public_id,
            )
            current = (
                ManualEffectiveValue.objects.select_for_update()
                .filter(
                    organization_id=actor.organization_id,
                    public_id=self.manual_value_public_id,
                    status=ManualEffectiveValueStatus.ACTIVE,
                    active_slot=1,
                )
                .first()
            )
            if current is None:
                raise ValidationFailedError(message="Active manual value not found.")
            current.status = ManualEffectiveValueStatus.REVOKED
            current.active_slot = None
            current.valid_to = now
            current.reason = self.reason
            current.save(
                update_fields=["status", "active_slot", "valid_to", "reason", "updated_at"]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="manual_effective_value.revoke",
                    resource_type="operating_value",
                    resource_public_id=current.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={"reason": self.reason},
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            return current
