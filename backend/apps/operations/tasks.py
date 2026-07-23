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
    ``ExecuteRetirementPlan`` once per distinct plan found. This task never
    decides retirement: the plan was already approved through the dual-control
    gate; the task only carries out dates that have arrived (and retries
    transient action failures), exactly as ``ExecuteRetirementPlan`` would if
    triggered manually.

    The plan's creator is used as the executing actor. Retirement plan
    creation and execution are granted to the same role (OPERATING_SUPERVISOR)
    so this stays within the existing RBAC model instead of introducing a
    bypass; if that grant is ever missing, ExecuteRetirementPlan raises
    PermissionDeniedError and the failure is surfaced rather than swallowed.

    Idempotent and safe under concurrent/duplicate execution: actions are
    scanned again on every call, but ``ExecuteRetirementPlan`` locks the plan
    and its actions with ``select_for_update`` and skips already-COMPLETED
    actions/plans, so re-running (or two workers racing on the same due plan)
    cannot double-complete an action or reopen a completed plan.
    """
    from apps.operations.models import (
        RetirementActionStatus,
        RetirementExecutionAction,
        RetirementPlan,
    )
    from apps.operations.services.retirement_plans import ExecuteRetirementPlan
    from apps.platform.application.command import CommandContext

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
        plan = RetirementPlan.objects.select_related("created_by").filter(pk=plan_id).first()
        if plan is None:
            continue
        try:
            ExecuteRetirementPlan(
                context=CommandContext.for_actor(plan.created_by),
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
