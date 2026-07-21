"""Write OperatingFact versions from validated ingestion rows."""

from __future__ import annotations

from apps.integrations.models import IngestionBatch, IngestionRow, IngestionRowStatus
from apps.operations.models import (
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    OperatingFact,
    OperatingFactStatus,
)


def _resolve_metric(row: IngestionRow) -> MetricDefinitionVersion | None:
    if row.metric_definition_id is not None:
        return row.metric_definition
    if not row.metric_code:
        return None
    return (
        MetricDefinitionVersion.objects.filter(
            organization_id=row.organization_id,
            metric_code=row.metric_code,
            status=MetricDefinitionStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )


def import_row_as_fact(
    *, batch: IngestionBatch, row: IngestionRow
) -> tuple[str, OperatingFact | None]:
    """Return ('added'|'revision'|'skipped'|'error', fact_or_none)."""
    if row.status in {IngestionRowStatus.ERROR, IngestionRowStatus.UNMAPPED}:
        return "skipped", None
    if row.status not in {IngestionRowStatus.VALID, IngestionRowStatus.WARNING}:
        return "skipped", None
    if row.sku_id is None or row.channel_id is None:
        return "error", None
    metric = _resolve_metric(row)
    if metric is None or row.period_start is None or row.period_end is None:
        return "error", None
    if row.source_timestamp is None:
        return "error", None

    current = (
        OperatingFact.objects.select_for_update()
        .filter(
            source=batch.source,
            source_record_key=row.external_record_key,
            metric_definition=metric,
            sku_id=row.sku_id,
            channel_id=row.channel_id,
            period_granularity=row.period_granularity,
            period_start=row.period_start,
            period_end=row.period_end,
            active_slot=1,
            fact_status=OperatingFactStatus.VALID,
        )
        .first()
    )
    if current is not None:
        current.fact_status = OperatingFactStatus.SUPERSEDED
        current.active_slot = None
        current.save(update_fields=["fact_status", "active_slot", "updated_at"])
        fact = OperatingFact.objects.create(
            organization_id=batch.organization_id,
            sku_id=row.sku_id,
            channel_id=row.channel_id,
            metric_definition=metric,
            period_granularity=row.period_granularity,
            period_start=row.period_start,
            period_end=row.period_end,
            numeric_value=row.numeric_value,
            text_value=row.text_value,
            unit=row.unit,
            currency=row.currency,
            source=batch.source,
            batch=batch,
            source_record_key=row.external_record_key,
            fact_status=OperatingFactStatus.VALID,
            active_slot=1,
            source_timestamp=row.source_timestamp,
        )
        return "revision", fact

    fact = OperatingFact.objects.create(
        organization_id=batch.organization_id,
        sku_id=row.sku_id,
        channel_id=row.channel_id,
        metric_definition=metric,
        period_granularity=row.period_granularity,
        period_start=row.period_start,
        period_end=row.period_end,
        numeric_value=row.numeric_value,
        text_value=row.text_value,
        unit=row.unit,
        currency=row.currency,
        source=batch.source,
        batch=batch,
        source_record_key=row.external_record_key,
        fact_status=OperatingFactStatus.VALID,
        active_slot=1,
        source_timestamp=row.source_timestamp,
    )
    return "added", fact
