"""Rebuildable metric aggregates with controlled calculator registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.operations.models import (
    AggregateGrainType,
    AggregateStatus,
    CalculationType,
    ManualEffectiveValue,
    ManualEffectiveValueStatus,
    MetricAggregate,
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    OperatingFact,
    OperatingFactStatus,
)
from apps.products.models import SKU, ChannelConfiguration, ProductAsset


class AggregateCalculator(Protocol):
    def combine(self, values: list[Decimal]) -> Decimal | None: ...


class SumCalculator:
    def combine(self, values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return sum(values, Decimal("0"))


class AverageCalculator:
    def combine(self, values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.000001"))


class LastCalculator:
    """LAST is applied on ordered contributions; combine receives already-sorted last value."""

    def combine(self, values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return values[-1]


CALCULATOR_REGISTRY: dict[str, AggregateCalculator] = {
    CalculationType.SUM: SumCalculator(),
    CalculationType.AVERAGE: AverageCalculator(),
    CalculationType.LAST: LastCalculator(),
}


@dataclass(frozen=True)
class _Cell:
    organization_id: int
    sku_id: int
    sku_public_id: UUID
    product_id: int
    product_public_id: UUID
    channel_id: int
    channel_public_id: UUID
    metric: MetricDefinitionVersion
    period_granularity: str
    period_start: date
    period_end: date
    numeric_value: Decimal
    unit: str
    currency: str
    is_manual: bool
    source_timestamp: datetime
    contributor: dict[str, Any]


def _parse_period(value: str | date) -> date:
    if isinstance(value, date):
        return value
    parsed = parse_date(value)
    if parsed is None:
        raise ValueError(f"Invalid date: {value}")
    return parsed


def _channel_key(channel: ChannelConfiguration | None) -> str:
    if channel is None:
        return "ALL"
    return str(channel.public_id)


def _minimum_coverage(metric: MetricDefinitionVersion) -> Decimal:
    raw = (metric.coverage_requirement or {}).get("minimum_rate", "0")
    return Decimal(str(raw))


def _load_effective_cells(
    *,
    organization_id: int,
    metric: MetricDefinitionVersion,
    period_granularity: str,
    period_start: date,
    period_end: date,
    sku_ids: set[int] | None = None,
) -> list[_Cell]:
    facts_qs = OperatingFact.objects.filter(
        organization_id=organization_id,
        metric_definition=metric,
        period_granularity=period_granularity,
        period_start=period_start,
        period_end=period_end,
        fact_status=OperatingFactStatus.VALID,
        active_slot=1,
    ).select_related(
        "sku", "sku__product_version", "sku__product_version__product", "channel", "source"
    )
    if sku_ids is not None:
        facts_qs = facts_qs.filter(sku_id__in=sku_ids)

    manuals = {
        (m.sku_id, m.channel_id): m
        for m in ManualEffectiveValue.objects.filter(
            organization_id=organization_id,
            metric_definition=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            status=ManualEffectiveValueStatus.ACTIVE,
            active_slot=1,
        )
    }

    # Prefer highest source priority + latest timestamp per sku/channel (same as resolve)
    best_facts: dict[tuple[int, int], OperatingFact] = {}
    for fact in facts_qs:
        key = (fact.sku_id, fact.channel_id)
        existing = best_facts.get(key)
        if existing is None:
            best_facts[key] = fact
            continue
        fact_rank = (fact.source.locked_source_priority(), fact.source_timestamp)
        existing_rank = (existing.source.locked_source_priority(), existing.source_timestamp)
        if fact_rank > existing_rank:
            best_facts[key] = fact

    cells: list[_Cell] = []
    for (sku_id, channel_id), fact in best_facts.items():
        manual = manuals.get((sku_id, channel_id))
        product = fact.sku.product_version.product
        if manual is not None:
            value = manual.numeric_value
            is_manual = True
            contributor = {
                "type": "MANUAL",
                "public_id": str(manual.public_id),
                "sku_public_id": str(fact.sku.public_id),
                "channel_public_id": str(fact.channel.public_id),
                "numeric_value": str(value) if value is not None else None,
                "is_manual": True,
                "fact_public_id": str(fact.public_id),
            }
            ts = manual.confirmed_at
        else:
            value = fact.numeric_value
            is_manual = False
            contributor = {
                "type": "FACT",
                "public_id": str(fact.public_id),
                "sku_public_id": str(fact.sku.public_id),
                "channel_public_id": str(fact.channel.public_id),
                "numeric_value": str(value) if value is not None else None,
                "is_manual": False,
            }
            ts = fact.source_timestamp
        if value is None:
            continue
        cells.append(
            _Cell(
                organization_id=organization_id,
                sku_id=sku_id,
                sku_public_id=fact.sku.public_id,
                product_id=product.id,
                product_public_id=product.public_id,
                channel_id=channel_id,
                channel_public_id=fact.channel.public_id,
                metric=metric,
                period_granularity=period_granularity,
                period_start=period_start,
                period_end=period_end,
                numeric_value=value,
                unit=fact.unit,
                currency=fact.currency,
                is_manual=is_manual,
                source_timestamp=ts,
                contributor=contributor,
            )
        )
    return cells


def _compatible(cells: list[_Cell]) -> bool:
    if not cells:
        return True
    units = {c.unit for c in cells}
    currencies = {c.currency for c in cells}
    return len(units) <= 1 and len(currencies) <= 1


def _combine_values(metric: MetricDefinitionVersion, cells: list[_Cell]) -> Decimal | None:
    if metric.calculation_type == CalculationType.LAST:
        ordered = sorted(cells, key=lambda c: c.source_timestamp)
        return CALCULATOR_REGISTRY[CalculationType.LAST].combine([c.numeric_value for c in ordered])
    calculator = CALCULATOR_REGISTRY.get(metric.calculation_type)
    if calculator is None:
        return None
    return calculator.combine([c.numeric_value for c in cells])


def _ratio_value(
    *,
    organization_id: int,
    metric: MetricDefinitionVersion,
    period_granularity: str,
    period_start: date,
    period_end: date,
    grain_type: str,
    grain_id: UUID,
    channel_id: int | None,
) -> tuple[Decimal | None, str, list[dict[str, Any]], bool, Decimal, int]:
    params = metric.parameters_json or {}
    num_code = params.get("numerator_metric_code")
    den_code = params.get("denominator_metric_code")
    if not num_code or not den_code:
        return None, AggregateStatus.INSUFFICIENT, [], False, Decimal("0"), 0

    num_metric = (
        MetricDefinitionVersion.objects.filter(
            organization_id=organization_id,
            metric_code=num_code,
            status=MetricDefinitionStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )
    den_metric = (
        MetricDefinitionVersion.objects.filter(
            organization_id=organization_id,
            metric_code=den_code,
            status=MetricDefinitionStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )
    if num_metric is None or den_metric is None:
        return None, AggregateStatus.INSUFFICIENT, [], False, Decimal("0"), 0

    def _pick(metric_def: MetricDefinitionVersion) -> MetricAggregate | None:
        qs = MetricAggregate.objects.filter(
            organization_id=organization_id,
            grain_type=grain_type,
            grain_id=grain_id,
            metric_definition=metric_def,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
        )
        if channel_id is None:
            qs = qs.filter(channel_key="ALL")
        else:
            qs = qs.filter(channel_id=channel_id)
        return qs.first()

    num_agg = _pick(num_metric)
    den_agg = _pick(den_metric)
    if num_agg is None or den_agg is None:
        return None, AggregateStatus.INSUFFICIENT, [], False, Decimal("0"), 0
    if (
        num_agg.status == AggregateStatus.NOT_COMPARABLE
        or den_agg.status == AggregateStatus.NOT_COMPARABLE
    ):
        return None, AggregateStatus.NOT_COMPARABLE, [], False, Decimal("0"), 0
    if (
        num_agg.status == AggregateStatus.INSUFFICIENT
        or den_agg.status == AggregateStatus.INSUFFICIENT
    ):
        coverage = min(num_agg.coverage_rate, den_agg.coverage_rate)
        return None, AggregateStatus.INSUFFICIENT, [], False, coverage, 0
    if num_agg.value is None or den_agg.value is None or den_agg.value == 0:
        return None, AggregateStatus.INSUFFICIENT, [], False, Decimal("0"), 0

    value = (num_agg.value / den_agg.value).quantize(Decimal("0.000001"))
    contributors = list(num_agg.contributors_json) + list(den_agg.contributors_json)
    has_manual = num_agg.has_manual_value or den_agg.has_manual_value
    coverage = min(num_agg.coverage_rate, den_agg.coverage_rate)
    status = AggregateStatus.OK
    if coverage < _minimum_coverage(metric):
        status = AggregateStatus.INSUFFICIENT
    return (
        value,
        status,
        contributors,
        has_manual,
        coverage,
        num_agg.source_count + den_agg.source_count,
    )


def _expected_channel_count(*, organization_id: int, sku_ids: set[int]) -> int:
    return ChannelConfiguration.objects.filter(
        organization_id=organization_id,
        sku_id__in=sku_ids,
    ).count()


def _upsert_aggregate(
    *,
    organization_id: int,
    grain_type: str,
    grain_id: UUID,
    channel: ChannelConfiguration | None,
    metric: MetricDefinitionVersion,
    period_granularity: str,
    period_start: date,
    period_end: date,
    value: Decimal | None,
    unit: str,
    currency: str,
    status: str,
    coverage_rate: Decimal,
    source_count: int,
    has_manual_value: bool,
    contributors: list[dict[str, Any]],
    calculated_at: datetime,
    calculation_run_id: UUID,
) -> MetricAggregate:
    channel_key = _channel_key(channel)
    defaults = {
        "channel": channel,
        "value": value,
        "unit": unit,
        "currency": currency,
        "status": status,
        "coverage_rate": coverage_rate,
        "source_count": source_count,
        "has_manual_value": has_manual_value,
        "contributors_json": contributors,
        "calculated_at": calculated_at,
        "calculation_run_id": calculation_run_id,
    }
    obj, _created = MetricAggregate.objects.update_or_create(
        organization_id=organization_id,
        grain_type=grain_type,
        grain_id=grain_id,
        channel_key=channel_key,
        metric_definition=metric,
        period_granularity=period_granularity,
        period_start=period_start,
        period_end=period_end,
        defaults=defaults,
    )
    return obj


def _aggregate_group(
    *,
    cells: list[_Cell],
    metric: MetricDefinitionVersion,
    grain_type: str,
    grain_id: UUID,
    channel: ChannelConfiguration | None,
    expected_channels: int,
    calculated_at: datetime,
    calculation_run_id: UUID,
    period_granularity: str,
    period_start: date,
    period_end: date,
    organization_id: int,
) -> MetricAggregate:
    present = len(cells)
    coverage = (
        (Decimal(present) / Decimal(expected_channels)).quantize(Decimal("0.000001"))
        if expected_channels > 0
        else Decimal("0")
    )
    contributors = [c.contributor for c in cells]
    has_manual = any(c.is_manual for c in cells)

    if not cells:
        return _upsert_aggregate(
            organization_id=organization_id,
            grain_type=grain_type,
            grain_id=grain_id,
            channel=channel,
            metric=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            value=None,
            unit="",
            currency="",
            status=AggregateStatus.INSUFFICIENT,
            coverage_rate=coverage,
            source_count=0,
            has_manual_value=False,
            contributors=[],
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
        )

    if not _compatible(cells):
        return _upsert_aggregate(
            organization_id=organization_id,
            grain_type=grain_type,
            grain_id=grain_id,
            channel=channel,
            metric=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            value=None,
            unit="",
            currency="",
            status=AggregateStatus.NOT_COMPARABLE,
            coverage_rate=coverage,
            source_count=present,
            has_manual_value=has_manual,
            contributors=contributors,
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
        )

    value = _combine_values(metric, cells)
    status = AggregateStatus.OK
    if coverage < _minimum_coverage(metric):
        status = AggregateStatus.INSUFFICIENT

    return _upsert_aggregate(
        organization_id=organization_id,
        grain_type=grain_type,
        grain_id=grain_id,
        channel=channel,
        metric=metric,
        period_granularity=period_granularity,
        period_start=period_start,
        period_end=period_end,
        value=value,
        unit=cells[0].unit,
        currency=cells[0].currency,
        status=status,
        coverage_rate=coverage,
        source_count=present,
        has_manual_value=has_manual,
        contributors=contributors,
        calculated_at=calculated_at,
        calculation_run_id=calculation_run_id,
    )


def _recalculate_standard_metric(
    *,
    organization_id: int,
    metric: MetricDefinitionVersion,
    period_granularity: str,
    period_start: date,
    period_end: date,
    sku_filter: set[int] | None,
    calculated_at: datetime,
    calculation_run_id: UUID,
) -> int:
    cells = _load_effective_cells(
        organization_id=organization_id,
        metric=metric,
        period_granularity=period_granularity,
        period_start=period_start,
        period_end=period_end,
        sku_ids=sku_filter,
    )
    written = 0

    # Base grain: SKU × channel
    by_sku_channel: dict[tuple[int, int], list[_Cell]] = {}
    for cell in cells:
        by_sku_channel.setdefault((cell.sku_id, cell.channel_id), []).append(cell)

    skus = {
        sku.id: sku
        for sku in SKU.objects.filter(
            organization_id=organization_id,
            id__in={c.sku_id for c in cells} | (sku_filter or set()),
        ).select_related("product_version", "product_version__product")
    }
    channels = {
        ch.id: ch
        for ch in ChannelConfiguration.objects.filter(
            organization_id=organization_id,
            id__in={c.channel_id for c in cells},
        )
    }

    # Ensure we know expected channels even when some cells missing
    target_sku_ids = set(sku_filter) if sku_filter else set(skus.keys())
    if not target_sku_ids and cells:
        target_sku_ids = {c.sku_id for c in cells}
    if not target_sku_ids:
        # Fall back to all SKUs that have facts for this metric/period or org products — skip
        target_sku_ids = set(
            OperatingFact.objects.filter(
                organization_id=organization_id,
                metric_definition=metric,
                period_granularity=period_granularity,
                period_start=period_start,
                period_end=period_end,
            ).values_list("sku_id", flat=True)
        )

    skus.update(
        {
            sku.id: sku
            for sku in SKU.objects.filter(
                organization_id=organization_id, id__in=target_sku_ids
            ).select_related("product_version", "product_version__product")
        }
    )
    all_channels_for_skus = list(
        ChannelConfiguration.objects.filter(
            organization_id=organization_id, sku_id__in=target_sku_ids
        )
    )
    channels.update({ch.id: ch for ch in all_channels_for_skus})

    for sku_id, channel_id in {(c.sku_id, c.channel_id) for c in cells}:
        group = by_sku_channel[(sku_id, channel_id)]
        sku = skus[sku_id]
        channel = channels[channel_id]
        _aggregate_group(
            cells=group,
            metric=metric,
            grain_type=AggregateGrainType.SKU,
            grain_id=sku.public_id,
            channel=channel,
            expected_channels=1,
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            organization_id=organization_id,
        )
        written += 1

    # SKU rollup across channels
    by_sku: dict[int, list[_Cell]] = {}
    for cell in cells:
        by_sku.setdefault(cell.sku_id, []).append(cell)

    for sku_id, sku in skus.items():
        if sku_id not in target_sku_ids:
            continue
        group = by_sku.get(sku_id, [])
        expected = _expected_channel_count(organization_id=organization_id, sku_ids={sku_id})
        if not group and expected == 0:
            continue
        if not group:
            _upsert_aggregate(
                organization_id=organization_id,
                grain_type=AggregateGrainType.SKU,
                grain_id=sku.public_id,
                channel=None,
                metric=metric,
                period_granularity=period_granularity,
                period_start=period_start,
                period_end=period_end,
                value=None,
                unit="",
                currency="",
                status=AggregateStatus.INSUFFICIENT,
                coverage_rate=Decimal("0"),
                source_count=0,
                has_manual_value=False,
                contributors=[],
                calculated_at=calculated_at,
                calculation_run_id=calculation_run_id,
            )
            written += 1
            continue
        _aggregate_group(
            cells=group,
            metric=metric,
            grain_type=AggregateGrainType.SKU,
            grain_id=sku.public_id,
            channel=None,
            expected_channels=expected,
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            organization_id=organization_id,
        )
        written += 1

    # PRODUCT rollup
    products: dict[int, ProductAsset] = {}
    by_product: dict[int, list[_Cell]] = {}
    for cell in cells:
        by_product.setdefault(cell.product_id, []).append(cell)
        products[cell.product_id] = ProductAsset.objects.get(pk=cell.product_id)

    # Include products for target skus even without cells
    for sku in skus.values():
        product = sku.product_version.product
        products[product.id] = product
        by_product.setdefault(product.id, [])

    for product_id, product in products.items():
        product_sku_ids = set(
            SKU.objects.filter(
                organization_id=organization_id,
                product_version__product_id=product_id,
            ).values_list("id", flat=True)
        )
        if sku_filter is not None and not (product_sku_ids & sku_filter):
            # Still roll up if any of our cells belong to product
            if product_id not in by_product or not by_product[product_id]:
                continue
        group = by_product.get(product_id, [])
        # Restrict group to product skus
        group = [c for c in group if c.sku_id in product_sku_ids]
        expected = _expected_channel_count(organization_id=organization_id, sku_ids=product_sku_ids)
        if not group and expected == 0:
            continue
        if not group:
            continue
        _aggregate_group(
            cells=group,
            metric=metric,
            grain_type=AggregateGrainType.PRODUCT,
            grain_id=product.public_id,
            channel=None,
            expected_channels=expected,
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            organization_id=organization_id,
        )
        written += 1

    return written


def _recalculate_ratio_metric(
    *,
    organization_id: int,
    metric: MetricDefinitionVersion,
    period_granularity: str,
    period_start: date,
    period_end: date,
    calculated_at: datetime,
    calculation_run_id: UUID,
) -> int:
    # Ensure numerator/denominator aggregates exist first
    params = metric.parameters_json or {}
    for code in (params.get("numerator_metric_code"), params.get("denominator_metric_code")):
        if not code:
            continue
        part = (
            MetricDefinitionVersion.objects.filter(
                organization_id=organization_id,
                metric_code=code,
                status=MetricDefinitionStatus.PUBLISHED,
            )
            .order_by("-version_number")
            .first()
        )
        if part is not None and part.calculation_type != CalculationType.RATIO:
            _recalculate_standard_metric(
                organization_id=organization_id,
                metric=part,
                period_granularity=period_granularity,
                period_start=period_start,
                period_end=period_end,
                sku_filter=None,
                calculated_at=calculated_at,
                calculation_run_id=calculation_run_id,
            )

    written = 0
    # Derive grains from denominator aggregates
    den_code = params.get("denominator_metric_code")
    den_metric = (
        MetricDefinitionVersion.objects.filter(
            organization_id=organization_id,
            metric_code=den_code,
            status=MetricDefinitionStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
        if den_code
        else None
    )
    if den_metric is None:
        return 0

    bases = MetricAggregate.objects.filter(
        organization_id=organization_id,
        metric_definition=den_metric,
        period_granularity=period_granularity,
        period_start=period_start,
        period_end=period_end,
    )
    for base in bases:
        value, status, contributors, has_manual, coverage, source_count = _ratio_value(
            organization_id=organization_id,
            metric=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            grain_type=base.grain_type,
            grain_id=base.grain_id,
            channel_id=base.channel_id,
        )
        _upsert_aggregate(
            organization_id=organization_id,
            grain_type=base.grain_type,
            grain_id=base.grain_id,
            channel=base.channel,
            metric=metric,
            period_granularity=period_granularity,
            period_start=period_start,
            period_end=period_end,
            value=value,
            unit=metric.unit,
            currency=metric.currency,
            status=status,
            coverage_rate=coverage,
            source_count=source_count,
            has_manual_value=has_manual,
            contributors=contributors,
            calculated_at=calculated_at,
            calculation_run_id=calculation_run_id,
        )
        written += 1
    return written


@dataclass
class RecalculateMetricAggregates:
    calculation_run_id: UUID
    affected_keys: list[dict[str, Any]]

    def execute(self) -> int:
        calculated_at = timezone.now()
        total = 0
        with transaction.atomic():
            for key in self.affected_keys:
                organization_id = int(key["organization_id"])
                metric_code = key["metric_code"]
                period_granularity = key["period_granularity"]
                period_start = _parse_period(key["period_start"])
                period_end = _parse_period(key["period_end"])
                sku_filter: set[int] | None = None
                if key.get("sku_public_id"):
                    sku = SKU.objects.filter(
                        organization_id=organization_id,
                        public_id=key["sku_public_id"],
                    ).first()
                    if sku is not None:
                        sku_filter = {sku.id}

                metric = (
                    MetricDefinitionVersion.objects.filter(
                        organization_id=organization_id,
                        metric_code=metric_code,
                        status=MetricDefinitionStatus.PUBLISHED,
                    )
                    .order_by("-version_number")
                    .first()
                )
                if metric is None:
                    continue

                if metric.calculation_type == CalculationType.RATIO:
                    total += _recalculate_ratio_metric(
                        organization_id=organization_id,
                        metric=metric,
                        period_granularity=period_granularity,
                        period_start=period_start,
                        period_end=period_end,
                        calculated_at=calculated_at,
                        calculation_run_id=self.calculation_run_id,
                    )
                else:
                    total += _recalculate_standard_metric(
                        organization_id=organization_id,
                        metric=metric,
                        period_granularity=period_granularity,
                        period_start=period_start,
                        period_end=period_end,
                        sku_filter=sku_filter,
                        calculated_at=calculated_at,
                        calculation_run_id=self.calculation_run_id,
                    )
        return total
