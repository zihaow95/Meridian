"""Overdue scan emits todos/outbox without mutating business status (EXE-012)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.models.department import Department, DepartmentStatus
from apps.notifications.models import Todo
from apps.platform.outbox.models import OutboxEvent
from apps.projects.models import Project
from apps.work_items.models import Task, TaskStatus
from apps.work_items.tasks import scan_execution_overdue


@pytest.mark.django_db
def test_overdue_scan_creates_todo_without_changing_task_status(project: Project) -> None:
    dept = Department.objects.create(
        organization=project.organization,
        department_code="OV",
        name="Overdue Dept",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )
    task = Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-OVERDUE",
        name="Late task",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=dept,
        responsible_user=project.leader,
        status=TaskStatus.IN_PROGRESS,
        planned_due_at=timezone.now() - timedelta(days=1),
        version_no=1,
    )

    scan_execution_overdue(now=timezone.now())
    task.refresh_from_db()
    assert task.status == TaskStatus.IN_PROGRESS
    assert Todo.objects.filter(
        source_id=task.public_id,
        todo_type="task.overdue",
        status="OPEN",
    ).count() == 1
    assert OutboxEvent.objects.filter(event_type="task.overdue").count() >= 1

    scan_execution_overdue(now=timezone.now())
    assert Todo.objects.filter(
        source_id=task.public_id,
        todo_type="task.overdue",
        status="OPEN",
    ).count() == 1
