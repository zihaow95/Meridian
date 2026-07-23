"""Bounded operating summary queries over MetricAggregate rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import DataSensitivityLevel, RoleStatus
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.models import AggregateGrainType, MetricAggregate, MonitoringScopeType
from apps.operations.policies.identity_provider import resolve_effective_assignments
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import SKU, ProductAsset

_READ_ACTION = "operating_fact.read"
_READ_LEVEL = DataSensitivityLevel.SENSITIVE_CONTROLLED


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
    sku_breakdown: list[dict] = field(default_factory=list)


@dataclass
class OperatingSummaryResult:
    items: list[OperatingSummaryItem]


def _authorize_resource(actor: User, *, public_id: UUID, metadata: dict[str, str]) -> None:
    decision = authorize(
        subject_for(actor),
        action=_READ_ACTION,
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=public_id,
            organization_id=actor.organization_id,
            sensitivity_level=_READ_LEVEL,
            metadata=metadata,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _has_org_wide_read(actor: User) -> bool:
    """Whether org-scoped RBAC alone (no monitoring assignment) grants operating_fact.read."""

    context = AuthorizationContext.current()
    return (
        RoleAssignment.objects.filter(
            user=actor,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=context.as_of,
            scope_type=ScopeType.ORGANIZATION,
            role__status=RoleStatus.ACTIVE,
            role__permissions__action__action_code=_READ_ACTION,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=context.as_of))
        .exists()
    )


def _allowed_channel_ids(
    actor: User, *, product: ProductAsset, sku: SKU | None
) -> set[int] | None:
    """Channel ids visible via MonitoringAssignment, or None when unrestricted."""

    if _has_org_wide_read(actor):
        return None

    channel_ids: set[int] = set()
    assignments = resolve_effective_assignments(user=actor, organization_id=actor.organization_id)
    for assignment in assignments:
        if assignment.product_id != product.id:
            continue
        if sku is not None and assignment.sku_id not in (None, sku.id):
            continue
        if assignment.scope_type in (MonitoringScopeType.PRODUCT, MonitoringScopeType.SKU):
            return None
        if assignment.scope_type == MonitoringScopeType.SKU_CHANNEL and assignment.channel_id:
            channel_ids.add(assignment.channel_id)
    return channel_ids


def _apply_channel_scope(
    qs: QuerySet[MetricAggregate], allowed_channel_ids: set[int] | None
) -> QuerySet[MetricAggregate]:
    if allowed_channel_ids is None:
        return qs
    if not allowed_channel_ids:
        return qs.none()
    return qs.filter(channel_id__in=allowed_channel_ids)


def _to_item(
    row: MetricAggregate,
    *,
    include_drilldown: bool,
    sku_breakdown: list[dict] | None = None,
) -> OperatingSummaryItem:
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
        sku_breakdown=sku_breakdown or [],
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
        sku = (
            SKU.objects.select_related("product_version__product")
            .filter(organization_id=actor.organization_id, public_id=self.sku_public_id)
            .first()
        )
        if sku is None:
            raise ValidationFailedError(message="SKU not found.")
        product = sku.product_version.product

        _authorize_resource(
            actor,
            public_id=sku.public_id,
            metadata={
                "product_public_id": str(product.public_id),
                "sku_public_id": str(sku.public_id),
            },
        )
        allowed_channel_ids = _allowed_channel_ids(actor, product=product, sku=sku)

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
        qs = _apply_channel_scope(qs, allowed_channel_ids)

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
        product = ProductAsset.objects.filter(
            organization_id=actor.organization_id,
            public_id=self.product_public_id,
        ).first()
        if product is None:
            raise ValidationFailedError(message="Product not found.")

        _authorize_resource(
            actor,
            public_id=product.public_id,
            metadata={"product_public_id": str(product.public_id)},
        )
        allowed_channel_ids = _allowed_channel_ids(actor, product=product, sku=None)

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
        qs = _apply_channel_scope(qs, allowed_channel_ids)

        sku_public_ids = list(
            SKU.objects.filter(
                organization_id=actor.organization_id,
                product_version__product_id=product.id,
            ).values_list("public_id", flat=True)
        )
        breakdown_map: dict[tuple[int, str], list[dict]] = {}
        if sku_public_ids:
            sku_qs = MetricAggregate.objects.filter(
                organization_id=actor.organization_id,
                grain_type=AggregateGrainType.SKU,
                grain_id__in=sku_public_ids,
                period_granularity=self.period_granularity,
                period_start=self.period_start,
                period_end=self.period_end,
            ).select_related("metric_definition")
            if self.metric_codes:
                sku_qs = sku_qs.filter(metric_definition__metric_code__in=self.metric_codes)
            sku_qs = _apply_channel_scope(sku_qs, allowed_channel_ids)
            for row in sku_qs:
                key = (row.metric_definition_id, row.channel_key)
                breakdown_map.setdefault(key, []).append(
                    {
                        "sku_public_id": str(row.grain_id),
                        "value": None if row.value is None else str(row.value),
                        "status": row.status,
                        "coverage_rate": str(row.coverage_rate),
                        "has_manual_value": row.has_manual_value,
                    }
                )

        items = [
            _to_item(
                row,
                include_drilldown=self.include_drilldown,
                sku_breakdown=breakdown_map.get((row.metric_definition_id, row.channel_key)),
            )
            for row in qs
        ]
        return OperatingSummaryResult(items=items)
