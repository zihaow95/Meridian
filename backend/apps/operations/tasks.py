"""Celery tasks for operations metric aggregate recalculation and retirement execution."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from celery import shared_task  # type: ignore[import-untyped]
from django.utils import timezone
from django.utils.dateparse import parse_date

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


@shared_task(name="operations.execute_due_retirement_actions")
def execute_due_retirement_actions_task(as_of: str | None = None) -> int:
    """Execute every due, previously-approved retirement plan (system-scheduled).

    Scans MySQL for PENDING or FAILED ``RetirementExecutionAction`` rows
    scheduled on or before ``as_of`` (default today), then runs
    ``ExecuteRetirementPlan`` once per distinct plan found using a controlled
    system executor principal. Plan creators remain audit provenance on the plan
    row; their current login status or grants must not block due execution.

    Idempotent under concurrent/duplicate runs via ``select_for_update`` inside
    ``ExecuteRetirementPlan``.
    """
    from apps.operations.models import (
        RetirementActionStatus,
        RetirementExecutionAction,
        RetirementPlan,
    )
    from apps.operations.services.retirement_plans import ExecuteRetirementPlan
    from apps.operations.services.system_actor import retirement_system_command_context

    as_of_date = parse_date(as_of) if as_of else timezone.now().date()
    if as_of_date is None:
        raise ValueError(f"Invalid as_of date: {as_of!r}")

    plan_ids = list(
        RetirementExecutionAction.objects.filter(
            status__in=(
                RetirementActionStatus.PENDING,
                RetirementActionStatus.FAILED,
            ),
            scheduled_for__lte=as_of_date,
        )
        .values_list("plan_id", flat=True)
        .distinct()
    )

    processed = 0
    failures: list[str] = []
    for plan_id in plan_ids:
        plan = RetirementPlan.objects.select_related("organization").filter(pk=plan_id).first()
        if plan is None:
            continue
        try:
            ExecuteRetirementPlan(
                context=retirement_system_command_context(plan.organization),
                plan_public_id=plan.public_id,
                as_of=as_of_date,
            ).execute()
        except Exception as exc:  # noqa: BLE001 - collected below, never swallowed
            failures.append(f"{plan.public_id}: {exc!r}")
            continue
        processed += 1

    if failures:
        raise RuntimeError(
            f"execute_due_retirement_actions_task processed {processed}/{len(plan_ids)} "
            f"due plans; failures={failures}"
        )
    return processed
