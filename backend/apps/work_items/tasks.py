"""Async overdue scanners for tasks and emergency executions."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.notifications.models import Todo, TodoStatus
from apps.notifications.services.todos import TodoEvent, UpsertOpenTodo
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.work_items.models import Task, TaskStatus


def scan_execution_overdue(*, now: datetime | None = None) -> int:
    """Emit overdue todos/outbox; never mutates task business status."""

    as_of = now or timezone.now()
    overdue_tasks = Task.objects.filter(
        planned_due_at__lt=as_of,
        status__in=[TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED],
        responsible_user_id__isnull=False,
    ).select_related("responsible_user", "project")

    created = 0
    for task in overdue_tasks:
        assignee = task.responsible_user
        if assignee is None:
            continue
        dedup_key = f"task.overdue:{task.public_id}"
        if Todo.objects.filter(
            assignee_id=assignee.id,
            dedup_key=dedup_key,
            status=TodoStatus.OPEN,
        ).exists():
            continue
        UpsertOpenTodo(
            event=TodoEvent(
                assignee_id=assignee.id,
                organization_id=task.organization_id,
                todo_type="task.overdue",
                source_type="task",
                source_id=task.public_id,
                action_code="task.update_own",
                dedup_key=dedup_key,
                deep_link=f"/projects/{task.project.public_id}/tasks/{task.public_id}",
                title=f"Overdue task: {task.name}",
                due_at=task.planned_due_at,
            )
        ).execute()
        register_outbox_event(
            OutboxMessage(
                event_type="task.overdue",
                aggregate_type="task",
                aggregate_id=task.public_id,
                payload={
                    "task_public_id": str(task.public_id),
                    "dedup_key": dedup_key,
                    "assignee_id": assignee.id,
                    "organization_id": task.organization_id,
                    "todo_type": "task.overdue",
                    "source_type": "task",
                    "source_id": str(task.public_id),
                    "action_code": "task.update_own",
                    "deep_link": f"/projects/{task.project.public_id}/tasks/{task.public_id}",
                    "title": f"Overdue task: {task.name}",
                },
                occurred_at=as_of,
            )
        )
        created += 1
    return created
