"""Operations local outbox consumers for risk signal and issue todos."""

from __future__ import annotations

from uuid import UUID

from apps.identity.models.user import User
from apps.notifications.services.todos import TodoEvent, UpsertOpenTodo
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    OperatingIssue,
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


def local_consumer_registry() -> dict[str, tuple[str, OutboxConsumer]]:
    return {
        "risk_signal.created": ("risk_signal_todo", RiskSignalCreatedConsumer()),
        "risk_signal.closed": ("risk_signal_closed", RiskSignalClosedConsumer()),
        "operating_issue.created": ("operating_issue_todo", OperatingIssueCreatedConsumer()),
        "operating_issue.decided": (
            "operating_issue_decision_todo",
            OperatingIssueDecidedConsumer(),
        ),
        "product_version.published": (
            "operating_issue_iteration_result",
            ProductVersionPublishedConsumer(),
        ),
    }
