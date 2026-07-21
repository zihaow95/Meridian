"""Celery tasks for operations metric aggregate recalculation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]

from apps.operations.services.aggregations import RecalculateMetricAggregates


@shared_task(name="operations.recalculate_metric_aggregates")
def recalculate_metric_aggregates_task(
    calculation_run_id: str,
    affected_keys: list[dict[str, Any]],
) -> int:
    """Recalculate aggregates from MySQL using business keys only (no detail payloads)."""
    return RecalculateMetricAggregates(
        calculation_run_id=UUID(str(calculation_run_id)),
        affected_keys=affected_keys,
    ).execute()
