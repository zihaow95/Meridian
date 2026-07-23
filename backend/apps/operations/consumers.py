"""Operations local outbox consumers for risk signal, issue, and recalc side effects."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.identity.models.user import User
from apps.notifications.services.todos import TodoEvent, UpsertOpenTodo
from apps.operations.models import (
    ManualEffectiveValue,
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    OperatingIssue,
    RetirementPlan,
    RiskSignal,
)
from apps.platform.outbox.consumer import OutboxConsumer
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import SKU


class RiskSignalCreatedConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "risk_signal.created":
            return
        payload = event.payload_json or {}
        signal_id = UUID(str(payload.get("signal_public_id") or event.aggregate_id))
        signal = RiskSignal.objects.filter(public_id=signal_id).select_related("channel").first()
        if signal is None:
            return
        sku = (
            SKU.objects.filter(public_id=signal.scope_id)
            .select_related("product_version__product")
            .first()
        )
        if sku is None:
            return
        product = sku.product_version.product
        assignments = MonitoringAssignment.objects.filter(
            organization_id=signal.organization_id,
            product=product,
            status=MonitoringAssignmentStatus.ACTIVE,
            active_slot=1,
        ).select_related("supervisor")
        for assignment in assignments:
            if assignment.sku_id and assignment.sku_id != sku.id:
                continue
            if (
                signal.channel_id
                and assignment.channel_id
                and assignment.channel_id != signal.channel_id
            ):
                continue
            UpsertOpenTodo(
                event=TodoEvent(
                    assignee_id=assignment.supervisor_id,
                    organization_id=signal.organization_id,
                    todo_type="risk_signal_review",
                    source_type="risk_signal",
                    source_id=signal.public_id,
                    action_code="risk_signal.read",
                    dedup_key=f"risk_signal.created:{signal.public_id}:{assignment.supervisor_id}",
                    deep_link=f"/operations/risk-signals/{signal.public_id}",
                    title=f"Risk signal {signal.scope_key}",
                )
            ).execute()


class RiskSignalClosedConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "risk_signal.closed":
            return
        return


class OperatingIssueCreatedConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "operating_issue.created":
            return
        payload = event.payload_json or {}
        issue_id = UUID(str(payload.get("issue_public_id") or event.aggregate_id))
        issue = OperatingIssue.objects.filter(public_id=issue_id).first()
        if issue is None:
            return
        UpsertOpenTodo(
            event=TodoEvent(
                assignee_id=issue.owner_id,
                organization_id=issue.organization_id,
                todo_type="operating_issue_review",
                source_type="operating_issue",
                source_id=issue.public_id,
                action_code="operating_issue.analyze",
                dedup_key=f"operating_issue.created:{issue.public_id}:{issue.owner_id}",
                deep_link=f"/operations/issues/{issue.public_id}",
                title=issue.title,
            )
        ).execute()


class OperatingIssueDecidedConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "operating_issue.decided":
            return
        payload = event.payload_json or {}
        responsible_id = payload.get("responsible_user_id")
        if responsible_id is None:
            return
        issue_id = UUID(str(payload.get("issue_public_id") or event.aggregate_id))
        issue = OperatingIssue.objects.filter(public_id=issue_id).first()
        if issue is None:
            return
        user = User.objects.filter(pk=int(responsible_id)).first()
        if user is None:
            return
        UpsertOpenTodo(
            event=TodoEvent(
                assignee_id=user.id,
                organization_id=issue.organization_id,
                todo_type="operating_issue_action",
                source_type="operating_issue",
                source_id=issue.public_id,
                action_code="operating_issue.analyze",
                dedup_key=(
                    f"operating_issue.decided:{issue.public_id}:"
                    f"{payload.get('decision_public_id')}:{user.id}"
                ),
                deep_link=f"/operations/issues/{issue.public_id}",
                title=f"Action: {issue.title}",
            )
        ).execute()


class ProductVersionPublishedConsumer:
    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "product_version.published":
            return
        from apps.operations.services.iteration_results import HandleProductVersionPublished

        HandleProductVersionPublished(
            event_id=event.event_id,
            payload=event.payload_json or {},
        ).execute()


class OperatingFactImportedConsumer:
    """Recalculates aggregates in-process for metric keys touched by an imported batch."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "operating_fact.imported":
            return
        from apps.integrations.models import IngestionBatch, IngestionRowStatus

        payload = event.payload_json or {}
        batch_id = payload.get("batch_public_id") or event.aggregate_id
        batch = IngestionBatch.objects.filter(public_id=UUID(str(batch_id))).first()
        if batch is None:
            return
        rows = (
            batch.rows.filter(status=IngestionRowStatus.IMPORTED)
            .exclude(metric_definition__isnull=True)
            .select_related("metric_definition", "sku")
        )
        seen: set[tuple[str, str, Any, Any, str | None]] = set()
        affected_keys: list[dict[str, Any]] = []
        for row in rows:
            sku_public_id = str(row.sku.public_id) if row.sku_id else None
            key = (
                row.metric_definition.metric_code,
                row.period_granularity,
                row.period_start,
                row.period_end,
                sku_public_id,
            )
            if key in seen:
                continue
            seen.add(key)
            affected_keys.append(
                {
                    "organization_id": batch.organization_id,
                    "metric_code": row.metric_definition.metric_code,
                    "period_granularity": row.period_granularity,
                    "period_start": row.period_start.isoformat(),
                    "period_end": row.period_end.isoformat(),
                    "sku_public_id": sku_public_id,
                }
            )
        if not affected_keys:
            return
        from apps.operations.services.aggregations import RecalculateMetricAggregates

        RecalculateMetricAggregates(
            calculation_run_id=event.event_id,
            affected_keys=affected_keys,
        ).execute()


class OperatingValueOverriddenConsumer:
    """Recalculates aggregates in-process for the metric key a manual value affects."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "operating_value.overridden":
            return
        payload = event.payload_json or {}
        value_id = payload.get("manual_value_public_id") or event.aggregate_id
        manual = (
            ManualEffectiveValue.objects.filter(public_id=UUID(str(value_id)))
            .select_related("metric_definition", "sku")
            .first()
        )
        if manual is None:
            return
        from apps.operations.services.aggregations import RecalculateMetricAggregates

        RecalculateMetricAggregates(
            calculation_run_id=event.event_id,
            affected_keys=[
                {
                    "organization_id": manual.organization_id,
                    "metric_code": manual.metric_definition.metric_code,
                    "period_granularity": manual.period_granularity,
                    "period_start": manual.period_start.isoformat(),
                    "period_end": manual.period_end.isoformat(),
                    "sku_public_id": str(manual.sku.public_id),
                }
            ],
        ).execute()


class MetricDefinitionPublishedAckConsumer:
    """No side effect yet; validates payload shape so the event reaches PUBLISHED."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "metric_definition.published":
            return
        payload = event.payload_json or {}
        if not payload.get("metric_code"):
            raise ValueError("metric_definition.published payload missing metric_code")


class MonitoringAssignmentUpdatedAckConsumer:
    """No side effect yet; validates payload shape so the event reaches PUBLISHED."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "monitoring_assignment.updated":
            return
        payload = event.payload_json or {}
        if not payload.get("assignment_public_id"):
            raise ValueError("monitoring_assignment.updated payload missing assignment_public_id")


class OperatingIssueConvertedAckConsumer:
    """No side effect yet; validates payload shape so the event reaches PUBLISHED."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "operating_issue.converted":
            return
        payload = event.payload_json or {}
        if not payload.get("issue_public_id"):
            raise ValueError("operating_issue.converted payload missing issue_public_id")


class RetirementApprovedAckConsumer:
    """No side effect yet; validates payload shape so the event reaches PUBLISHED.

    Execution itself is driven by the ``operations.execute_due_retirement_actions``
    beat task scanning ``RetirementExecutionAction`` rows directly, not by this event.
    """

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "retirement.approved":
            return
        payload = event.payload_json or {}
        plan_id = payload.get("plan_public_id")
        if not plan_id:
            raise ValueError("retirement.approved payload missing plan_public_id")
        if not RetirementPlan.objects.filter(public_id=UUID(str(plan_id))).exists():
            raise ValueError("retirement.approved plan_public_id does not resolve to a plan")


class RetirementExecutionFailedConsumer:
    """Notifies product supervisors when a scheduled retirement action fails."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "retirement.execution_failed":
            return
        payload = event.payload_json or {}
        plan_id = payload.get("plan_public_id") or event.aggregate_id
        plan = (
            RetirementPlan.objects.filter(public_id=UUID(str(plan_id)))
            .select_related("product")
            .first()
        )
        if plan is None:
            return
        assignments = MonitoringAssignment.objects.filter(
            organization_id=plan.organization_id,
            product=plan.product,
            status=MonitoringAssignmentStatus.ACTIVE,
            active_slot=1,
        ).select_related("supervisor")
        action_type = payload.get("action_type") or "UNKNOWN"
        for assignment in assignments:
            UpsertOpenTodo(
                event=TodoEvent(
                    assignee_id=assignment.supervisor_id,
                    organization_id=plan.organization_id,
                    todo_type="retirement_execution_failed",
                    source_type="retirement_plan",
                    source_id=plan.public_id,
                    action_code="retirement_plan.execute",
                    dedup_key=(
                        f"retirement.execution_failed:{plan.public_id}:"
                        f"{action_type}:{assignment.supervisor_id}"
                    ),
                    deep_link=f"/operations/retirement/{plan.public_id}",
                    title=f"Retirement execution failed: {plan.product.name}",
                )
            ).execute()


class RetirementCompletedAckConsumer:
    """No side effect yet; validates payload shape so the event reaches PUBLISHED."""

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "retirement.completed":
            return
        payload = event.payload_json or {}
        if not payload.get("plan_public_id"):
            raise ValueError("retirement.completed payload missing plan_public_id")


def local_consumer_registry() -> dict[str, list[tuple[str, OutboxConsumer]]]:
    return {
        "risk_signal.created": [("risk_signal_todo", RiskSignalCreatedConsumer())],
        "risk_signal.closed": [("risk_signal_closed", RiskSignalClosedConsumer())],
        "operating_issue.created": [("operating_issue_todo", OperatingIssueCreatedConsumer())],
        "operating_issue.decided": [
            ("operating_issue_decision_todo", OperatingIssueDecidedConsumer()),
        ],
        "product_version.published": [
            ("operating_issue_iteration_result", ProductVersionPublishedConsumer()),
        ],
        "operating_fact.imported": [
            ("operating_fact_recalc", OperatingFactImportedConsumer()),
        ],
        "operating_value.overridden": [
            ("operating_value_recalc", OperatingValueOverriddenConsumer()),
        ],
        "metric_definition.published": [
            ("metric_definition_published_ack", MetricDefinitionPublishedAckConsumer()),
        ],
        "monitoring_assignment.updated": [
            ("monitoring_assignment_updated_ack", MonitoringAssignmentUpdatedAckConsumer()),
        ],
        "operating_issue.converted": [
            ("operating_issue_converted_ack", OperatingIssueConvertedAckConsumer()),
        ],
        "retirement.approved": [
            ("retirement_approved_ack", RetirementApprovedAckConsumer()),
        ],
        "retirement.execution_failed": [
            ("retirement_execution_failed_todo", RetirementExecutionFailedConsumer()),
        ],
        "retirement.completed": [
            ("retirement_completed_ack", RetirementCompletedAckConsumer()),
        ],
    }
