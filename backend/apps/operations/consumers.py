"""Operations local outbox consumers for risk signal todos."""

from __future__ import annotations

from uuid import UUID

from apps.notifications.services.todos import TodoEvent, UpsertOpenTodo
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
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
        sku = SKU.objects.filter(public_id=signal.scope_id).select_related(
            "product_version__product"
        ).first()
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
        # Closed events are acknowledged for dispatch completion; no duplicate open todos.
        return


def local_consumer_registry() -> dict[str, tuple[str, OutboxConsumer]]:
    return {
        "risk_signal.created": ("risk_signal_todo", RiskSignalCreatedConsumer()),
        "risk_signal.closed": ("risk_signal_closed", RiskSignalClosedConsumer()),
    }
