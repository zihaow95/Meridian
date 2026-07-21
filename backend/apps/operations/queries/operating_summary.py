"""Bounded operating summary queries over MetricAggregate rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.models import AggregateGrainType, MetricAggregate
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import SKU, ProductAsset


@dataclass
class OperatingSummaryItem:
    grain_type: str
    grain_public_id: UUID
    channel_public_id: UUID | None
    metric_code: str
    metric_definition_public_id: UUID
    period_start: date
    period_end: date
    period_granularity: str
    value: Decimal | None
    status: str
    coverage_rate: Decimal
    source_count: int
    has_manual_value: bool
    calculated_at: datetime | None
    contributors: list[dict]


@dataclass
class OperatingSummaryResult:
    items: list[OperatingSummaryItem]


def _authorize_read(actor: User) -> None:
    decision = authorize(
        subject_for(actor),
        action="operating_fact.read",
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=None,
            organization_id=actor.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _to_item(row: MetricAggregate, *, include_drilldown: bool) -> OperatingSummaryItem:
    return OperatingSummaryItem(
        grain_type=row.grain_type,
        grain_public_id=row.grain_id,
        channel_public_id=row.channel.public_id if row.channel is not None else None,
        metric_code=row.metric_definition.metric_code,
        metric_definition_public_id=row.metric_definition.public_id,
        period_start=row.period_start,
        period_end=row.period_end,
        period_granularity=row.period_granularity,
        value=row.value,
        status=row.status,
        coverage_rate=row.coverage_rate,
        source_count=row.source_count,
        has_manual_value=row.has_manual_value,
        calculated_at=row.calculated_at,
        contributors=list(row.contributors_json) if include_drilldown else [],
    )


@dataclass
class QuerySkuOperatingSummary:
    context: CommandContext
    sku_public_id: UUID
    period_start: date
    period_end: date
    period_granularity: str
    metric_codes: list[str] | None = None
    include_drilldown: bool = False

    def execute(self) -> OperatingSummaryResult:
        actor = self.context.actor
        _authorize_read(actor)
        sku = SKU.objects.filter(
            organization_id=actor.organization_id,
            public_id=self.sku_public_id,
        ).first()
        if sku is None:
            raise ValidationFailedError(message="SKU not found.")

        qs = (
            MetricAggregate.objects.filter(
                organization_id=actor.organization_id,
                grain_type=AggregateGrainType.SKU,
                grain_id=sku.public_id,
                period_granularity=self.period_granularity,
                period_start=self.period_start,
                period_end=self.period_end,
            )
            .select_related("metric_definition", "channel")
            .order_by("metric_definition__metric_code", "channel_key")
        )
        if self.metric_codes:
            qs = qs.filter(metric_definition__metric_code__in=self.metric_codes)

        return OperatingSummaryResult(
            items=[_to_item(row, include_drilldown=self.include_drilldown) for row in qs]
        )


@dataclass
class QueryProductOperatingSummary:
    context: CommandContext
    product_public_id: UUID
    period_start: date
    period_end: date
    period_granularity: str
    metric_codes: list[str] | None = None
    include_drilldown: bool = False

    def execute(self) -> OperatingSummaryResult:
        actor = self.context.actor
        _authorize_read(actor)
        product = ProductAsset.objects.filter(
            organization_id=actor.organization_id,
            public_id=self.product_public_id,
        ).first()
        if product is None:
            raise ValidationFailedError(message="Product not found.")

        qs = (
            MetricAggregate.objects.filter(
                organization_id=actor.organization_id,
                grain_type=AggregateGrainType.PRODUCT,
                grain_id=product.public_id,
                period_granularity=self.period_granularity,
                period_start=self.period_start,
                period_end=self.period_end,
            )
            .select_related("metric_definition", "channel")
            .order_by("metric_definition__metric_code", "channel_key")
        )
        if self.metric_codes:
            qs = qs.filter(metric_definition__metric_code__in=self.metric_codes)

        return OperatingSummaryResult(
            items=[_to_item(row, include_drilldown=self.include_drilldown) for row in qs]
        )
