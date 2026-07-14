"""Concurrent task updates leave a single DB fact."""

from __future__ import annotations

import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.work_items.errors import TaskVersionConflict
from apps.work_items.models import Task, TaskStatus
from apps.work_items.services.manage_tasks import AssignTaskResponsible


@pytest.mark.django_db(transaction=True)
def test_concurrent_assign_only_one_succeeds(
    project: Project,
    organization: Organization,
    grant_action,
) -> None:
    dept = Department.objects.create(
        organization=organization,
        department_code="CONC",
        name="Concurrent",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )
    head = User.objects.create_user(
        organization=organization,
        display_name="Conc Head",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    worker_a = User.objects.create_user(
        organization=organization,
        display_name="Worker A",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    worker_b = User.objects.create_user(
        organization=organization,
        display_name="Worker B",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    grant_action(head, "task.assign_department_member", "task", role_code="DEPARTMENT_HEAD")
    task = Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-CONC",
        name="Concurrent task",
        source_type="TEMPLATE",
        is_core=False,
        responsible_department=dept,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )

    results: list[str] = []
    barrier = threading.Barrier(2)

    def _assign(user: User, label: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            AssignTaskResponsible(
                context=CommandContext.for_actor(head),
                task_public_id=task.public_id,
                user_public_id=user.public_id,
                version_no=1,
            ).execute()
            results.append(f"ok:{label}")
        except TaskVersionConflict:
            results.append(f"conflict:{label}")
        except Exception as exc:  # noqa: BLE001 - collect unexpected for assert
            results.append(f"error:{type(exc).__name__}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_assign, args=(worker_a, "a")),
        threading.Thread(target=_assign, args=(worker_b, "b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results)[0].startswith("conflict:") or sorted(results)[1].startswith("conflict:")
    assert any(item.startswith("ok:") for item in results)
    task.refresh_from_db()
    assert task.version_no == 2
    assert task.responsible_user_id in {worker_a.id, worker_b.id}
    assert (
        AuditEvent.objects.filter(
            action_code="task.assign_department_member",
            resource_public_id=task.public_id,
        ).count()
        == 1
    )
