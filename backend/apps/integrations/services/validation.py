"""Validate and map staged ingestion rows."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.integrations.models import IngestionBatch, IngestionRowStatus
from apps.operations.errors import (
    OperatingDataMappingRequired,
    OperatingDataStructureInvalid,
    OperatingUnitMismatch,
)
from apps.operations.models import MetricDefinitionStatus, MetricDefinitionVersion
from apps.products.models import SKU, ChannelConfiguration, SKUStatus

_ALLOWED_GRANULARITIES = frozenset({"DAY", "WEEK", "MONTH", "QUARTER"})


def apply_mapping(raw: dict[str, Any], mapping_rules: list[dict[str, str]]) -> dict[str, Any]:
    mapped: dict[str, Any] = dict(raw)
    for rule in mapping_rules:
        external = rule["external_field"]
        internal = rule["internal_field"]
        if external in raw:
            mapped[internal] = raw[external]
    return mapped


def _period_window_error(*, granularity: str, period_start: date, period_end: date) -> str | None:
    if granularity not in _ALLOWED_GRANULARITIES:
        return f"Unsupported period_granularity: {granularity}"
    if granularity == "DAY":
        if period_start != period_end:
            return "DAY periods require period_start == period_end."
        return None
    if granularity == "WEEK":
        if period_start.weekday() != 0:
            return "WEEK periods must start on Monday."
        if period_end != period_start + timedelta(days=6):
            return "WEEK periods must end on the following Sunday."
        return None
    if granularity == "MONTH":
        if period_start.day != 1:
            return "MONTH periods must start on the first day of the month."
        next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        expected_end = next_month - timedelta(days=1)
        if period_end != expected_end:
            return "MONTH periods must end on the last day of the month."
        return None
    if granularity == "QUARTER":
        if period_start.month not in (1, 4, 7, 10) or period_start.day != 1:
            return "QUARTER periods must start on Jan/Apr/Jul/Oct 1."
        end_month = period_start.month + 2
        next_q = date(
            period_start.year + (1 if end_month == 12 else 0),
            1 if end_month == 12 else end_month + 1,
            1,
        )
        expected_end = next_q - timedelta(days=1)
        if period_end != expected_end:
            return "QUARTER periods must end on the last day of the quarter."
        return None
    return f"Unsupported period_granularity: {granularity}"


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    parsed = parse_date(text[:10]) if len(text) >= 10 else parse_date(text)
    return parsed


def _as_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    text = str(value).strip()
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def validate_batch_rows(batch: IngestionBatch) -> IngestionBatch:
    mapping_rules = batch.source.locked_mapping_rules()
    ranges = batch.source.locked_reasonable_ranges()
    sales_range = ranges.get("sales_amount") or {}
    min_sales = _as_decimal(sales_range.get("min"))
    max_sales = _as_decimal(sales_range.get("max"))

    rows = list(batch.rows.order_by("row_number"))
    key_counts: dict[str, int] = {}
    for row in rows:
        key = row.external_record_key or ""
        if key:
            key_counts[key] = key_counts.get(key, 0) + 1

    warning_count = 0
    error_count = 0
    success_count = 0

    for row in rows:
        mapped = apply_mapping(row.raw_payload, mapping_rules)
        row.external_record_key = str(
            mapped.get("external_record_key") or row.external_record_key or ""
        ).strip()
        row.sku_code = str(mapped.get("sku_code") or "").strip()
        row.channel_code = str(mapped.get("channel_code") or "").strip()
        row.metric_code = str(mapped.get("metric_code") or "").strip()
        row.period_granularity = str(mapped.get("period_granularity") or "").strip()
        row.period_start = _as_date(mapped.get("period_start"))
        row.period_end = _as_date(mapped.get("period_end"))
        row.unit = str(mapped.get("unit") or "").strip()
        row.currency = str(mapped.get("currency") or "").strip()
        row.source_timestamp = _as_datetime(mapped.get("source_timestamp"))
        row.numeric_value = _as_decimal(mapped.get("numeric_value") or mapped.get("sales_amount"))
        row.text_value = str(mapped.get("text_value") or "")
        row.error_code = ""
        row.error_message = ""
        row.warning_message = ""
        row.sku = None
        row.channel = None
        row.metric_definition = None

        if row.external_record_key and key_counts.get(row.external_record_key, 0) > 1:
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingDataStructureInvalid.code
            row.error_message = "Duplicate external_record_key within batch."
            error_count += 1
            row.save()
            continue

        if not row.unit or not row.currency:
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingDataStructureInvalid.code
            row.error_message = "unit and currency are required."
            error_count += 1
            row.save()
            continue

        if (
            not row.period_granularity
            or row.period_start is None
            or row.period_end is None
            or row.source_timestamp is None
            or row.numeric_value is None
        ):
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingDataStructureInvalid.code
            row.error_message = "Required period/value/timestamp fields are missing."
            error_count += 1
            row.save()
            continue

        if row.period_start > row.period_end:
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingDataStructureInvalid.code
            row.error_message = "period_start must be on or before period_end."
            error_count += 1
            row.save()
            continue

        period_error = _period_window_error(
            granularity=row.period_granularity,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        if period_error:
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingDataStructureInvalid.code
            row.error_message = period_error
            error_count += 1
            row.save()
            continue

        sku = SKU.objects.filter(
            organization_id=batch.organization_id,
            sku_code=row.sku_code,
            status=SKUStatus.ACTIVE,
        ).first()
        if sku is None:
            row.status = IngestionRowStatus.UNMAPPED
            row.error_code = OperatingDataMappingRequired.code
            row.error_message = f"SKU not found: {row.sku_code}"
            error_count += 1
            row.save()
            continue

        channel = ChannelConfiguration.objects.filter(
            organization_id=batch.organization_id,
            sku=sku,
            channel_code=row.channel_code,
        ).first()
        if channel is None:
            row.status = IngestionRowStatus.UNMAPPED
            row.error_code = OperatingDataMappingRequired.code
            row.error_message = f"Channel not found: {row.channel_code}"
            error_count += 1
            row.save()
            continue

        metric = (
            MetricDefinitionVersion.objects.filter(
                organization_id=batch.organization_id,
                metric_code=row.metric_code,
                status=MetricDefinitionStatus.PUBLISHED,
            )
            .order_by("-version_number")
            .first()
        )

        row.sku = sku
        row.channel = channel
        row.metric_definition = metric
        # Missing published metric is resolved at confirm; validate still marks mapped rows.

        if metric is not None and (
            (metric.unit and row.unit and metric.unit != row.unit)
            or (metric.currency and row.currency and metric.currency != row.currency)
        ):
            row.status = IngestionRowStatus.ERROR
            row.error_code = OperatingUnitMismatch.code
            row.error_message = (
                f"Row unit/currency ({row.unit}/{row.currency}) does not match "
                f"published metric definition ({metric.unit}/{metric.currency})."
            )
            error_count += 1
            row.save()
            continue

        if min_sales is not None and row.numeric_value < min_sales:
            row.status = IngestionRowStatus.WARNING
            row.warning_message = "Value below reasonable range."
            warning_count += 1
        elif max_sales is not None and row.numeric_value > max_sales:
            row.status = IngestionRowStatus.WARNING
            row.warning_message = "Value above reasonable range."
            warning_count += 1
        else:
            row.status = IngestionRowStatus.VALID
            success_count += 1
        row.save()

    batch.total_count = len(rows)
    batch.success_count = success_count
    batch.warning_count = warning_count
    batch.error_count = error_count
    batch.skipped_count = 0
    return batch
