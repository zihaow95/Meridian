"""Async overdue scanners for tasks and emergency executions."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

from apps.notifications.models import Todo, TodoStatus
from apps.notifications.services.todos import TodoEvent, UpsertOpenTodo
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.models import EmergencyExecution, EmergencyExecutionStatus
from apps.stage_gates.models import GateStatus, StageGateInstance
from apps.work_items.models import (
    Deliverable,
    DeliverableStatus,
    ProfessionalConfirmation,
    ProfessionalConfirmationStatus,
    Task,
    TaskStatus,
)

_INCOMPLETE_DELIVERABLE_STATUSES = [
    DeliverableStatus.NOT_STARTED,
    DeliverableStatus.DRAFT,
    DeliverableStatus.SUBMITTED,
]

_INCOMPLETE_TASK_STATUSES = [
    TaskStatus.NOT_STARTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.BLOCKED,
]

_OVERDUE_GATE_STATUSES = [
    GateStatus.READY,
    GateStatus.OPEN,
    GateStatus.SUBMITTED,
]


def _emit_overdue_notification(
    *,
    assignee_id: int,
    organization_id: int,
    todo_type: str,
    source_type: str,
    source_id: UUID,
    action_code: str,
    dedup_key: str,
    deep_link: str,
    title: str,
    due_at: datetime | None,
    as_of: datetime,
    outbox_event_type: str,
) -> bool:
    if Todo.objects.filter(
        assignee_id=assignee_id,
        dedup_key=dedup_key,
        status=TodoStatus.OPEN,
    ).exists():
        return False
    UpsertOpenTodo(
        event=TodoEvent(
            assignee_id=assignee_id,
            organization_id=organization_id,
            todo_type=todo_type,
            source_type=source_type,
            source_id=source_id,
            action_code=action_code,
            dedup_key=dedup_key,
            deep_link=deep_link,
            title=title,
            due_at=due_at,
        )
    ).execute()
    register_outbox_event(
        OutboxMessage(
            event_type=outbox_event_type,
            aggregate_type=source_type,
            aggregate_id=source_id,
            payload={
                "dedup_key": dedup_key,
                "assignee_id": assignee_id,
                "organization_id": organization_id,
                "todo_type": todo_type,
                "source_type": source_type,
                "source_id": str(source_id),
                "action_code": action_code,
                "deep_link": deep_link,
                "title": title,
            },
            occurred_at=as_of,
        )
    )
    return True


def scan_execution_overdue(*, now: datetime | None = None) -> int:
    """Emit overdue todos/outbox; never mutates task business status."""

    as_of = now or timezone.now()
    created = 0

    overdue_tasks = Task.objects.filter(
        planned_due_at__lt=as_of,
        status__in=_INCOMPLETE_TASK_STATUSES,
    ).select_related("responsible_user", "project", "project__leader")

    for task in overdue_tasks:
        recipients: list[tuple[int, str]] = []
        if task.responsible_user_id is not None:
            recipients.append((task.responsible_user_id, "task.overdue"))
        leader = task.project.leader
        if leader is not None:
            recipients.append((leader.id, "task.overdue.leader"))
        deep_link = f"/projects/{task.project.public_id}/tasks/{task.public_id}"
        for assignee_id, todo_type in recipients:
            dedup_key = f"{todo_type}:{task.public_id}"
            if _emit_overdue_notification(
                assignee_id=assignee_id,
                organization_id=task.organization_id,
                todo_type=todo_type,
                source_type="task",
                source_id=task.public_id,
                action_code="task.update_own",
                dedup_key=dedup_key,
                deep_link=deep_link,
                title=f"Overdue task: {task.name}",
                due_at=task.planned_due_at,
                as_of=as_of,
                outbox_event_type="task.overdue",
            ):
                created += 1

    overdue_deliverables = Deliverable.objects.filter(
        status__in=_INCOMPLETE_DELIVERABLE_STATUSES,
        planned_due_at__lt=as_of,
    ).select_related(
        "project",
        "project__leader",
        "stage",
        "compiler_task",
        "compiler_task__responsible_user",
    )
    for deliverable in overdue_deliverables:
        created += _notify_deliverable_overdue(deliverable=deliverable, as_of=as_of)

    stage_due_deliverables = Deliverable.objects.filter(
        status__in=_INCOMPLETE_DELIVERABLE_STATUSES,
        planned_due_at__isnull=True,
        stage__planned_end_at__lt=as_of,
    ).select_related(
        "project",
        "project__leader",
        "stage",
        "compiler_task",
        "compiler_task__responsible_user",
    )
    for deliverable in stage_due_deliverables:
        created += _notify_deliverable_overdue(
            deliverable=deliverable,
            as_of=as_of,
            due_at=deliverable.stage.planned_end_at,
        )

    one_day_ago = as_of - timedelta(days=1)
    pending_confirmations = ProfessionalConfirmation.objects.filter(
        status=ProfessionalConfirmationStatus.PENDING,
    ).select_related(
        "confirmer",
        "deliverable_revision__deliverable__project",
        "deliverable_revision__deliverable__stage",
    )
    for confirmation in pending_confirmations:
        deliverable = confirmation.deliverable_revision.deliverable
        stage = deliverable.stage
        is_overdue = confirmation.created_at < one_day_ago
        if stage.planned_end_at is not None and stage.planned_end_at < as_of:
            is_overdue = True
        if not is_overdue:
            continue
        project = deliverable.project
        dedup_key = f"professional_confirmation.overdue:{confirmation.public_id}"
        if _emit_overdue_notification(
            assignee_id=confirmation.confirmer_id,
            organization_id=confirmation.organization_id,
            todo_type="professional_confirmation.overdue",
            source_type="professional_confirmation",
            source_id=confirmation.public_id,
            action_code="deliverable.confirm",
            dedup_key=dedup_key,
            deep_link=(f"/projects/{project.public_id}/deliverables/{deliverable.public_id}"),
            title=f"Pending confirmation: {deliverable.name}",
            due_at=stage.planned_end_at,
            as_of=as_of,
            outbox_event_type="professional_confirmation.overdue",
        ):
            created += 1

    overdue_gates = StageGateInstance.objects.filter(
        status__in=_OVERDUE_GATE_STATUSES,
        project_stage__planned_end_at__lt=as_of,
        project__isnull=False,
    ).select_related("project", "project__leader", "project_stage")
    for gate in overdue_gates:
        gate_project = gate.project
        gate_stage = gate.project_stage
        if gate_project is None or gate_stage is None:
            continue
        leader = gate_project.leader
        if leader is None:
            continue
        dedup_key = f"stage_gate.overdue:{gate.public_id}"
        if _emit_overdue_notification(
            assignee_id=leader.id,
            organization_id=gate.organization_id,
            todo_type="stage_gate.overdue",
            source_type="stage_gate",
            source_id=gate.public_id,
            action_code="gate.submit",
            dedup_key=dedup_key,
            deep_link=f"/projects/{gate_project.public_id}/gates/{gate.public_id}",
            title=f"Overdue stage gate: {gate.stage_code}",
            due_at=gate_stage.planned_end_at,
            as_of=as_of,
            outbox_event_type="stage_gate.overdue",
        ):
            created += 1

    overdue_emergencies = EmergencyExecution.objects.filter(
        status=EmergencyExecutionStatus.OPEN,
        due_at__lt=as_of,
    ).select_related("project", "project__leader", "initiated_by")
    for record in overdue_emergencies:
        record.status = EmergencyExecutionStatus.OVERDUE
        record.save(update_fields=["status", "updated_at"])
        deep_link = f"/projects/{record.project.public_id}/emergency-executions/{record.public_id}"
        for assignee_id, todo_type in (
            (record.initiated_by_id, "emergency_execution.overdue"),
            (record.project.leader_id, "emergency_execution.overdue.leader"),
        ):
            if assignee_id is None:
                continue
            dedup_key = f"{todo_type}:{record.public_id}"
            if _emit_overdue_notification(
                assignee_id=assignee_id,
                organization_id=record.organization_id,
                todo_type=todo_type,
                source_type="emergency_execution",
                source_id=record.public_id,
                action_code="emergency_execution.create",
                dedup_key=dedup_key,
                deep_link=deep_link,
                title=f"Overdue emergency execution: {record.subject_summary}",
                due_at=record.due_at,
                as_of=as_of,
                outbox_event_type="emergency_execution.overdue",
            ):
                created += 1

    return created


def _notify_deliverable_overdue(
    *,
    deliverable: Deliverable,
    as_of: datetime,
    due_at: datetime | None = None,
) -> int:
    created = 0
    effective_due = due_at if due_at is not None else deliverable.planned_due_at
    deep_link = f"/projects/{deliverable.project.public_id}/deliverables/{deliverable.public_id}"
    recipients: list[tuple[int, str]] = []
    leader = deliverable.project.leader
    if leader is not None:
        recipients.append((leader.id, "deliverable.overdue.leader"))
    responsible = None
    compiler_task = deliverable.compiler_task
    if compiler_task is not None:
        responsible = compiler_task.responsible_user
    if responsible is not None:
        recipients.append((responsible.id, "deliverable.overdue"))
    for assignee_id, todo_type in recipients:
        dedup_key = f"{todo_type}:{deliverable.public_id}"
        if _emit_overdue_notification(
            assignee_id=assignee_id,
            organization_id=deliverable.organization_id,
            todo_type=todo_type,
            source_type="deliverable",
            source_id=deliverable.public_id,
            action_code="deliverable.update",
            dedup_key=dedup_key,
            deep_link=deep_link,
            title=f"Overdue deliverable: {deliverable.name}",
            due_at=effective_due,
            as_of=as_of,
            outbox_event_type="deliverable.overdue",
        ):
            created += 1
    return created
