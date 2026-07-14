"""Task permission boundaries for department heads vs project leaders."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.work_items.models import Task, TaskStatus
from apps.work_items.services.manage_tasks import AssignTaskResponsible, TransitionTask


@pytest.fixture
def qa_department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="QA",
        name="QA",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def qa_head(
    organization: Organization,
    qa_department: Department,
    grant_action,
) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="QA Head",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=qa_department,
    )
    grant_action(
        user,
        "task.assign_department_member",
        "task",
        role_code="DEPARTMENT_HEAD",
    )
    return user


@pytest.fixture
def rd_task(project: Project, organization: Organization) -> Task:
    rd = Department.objects.create(
        organization=organization,
        department_code="RD-PERM",
        name="R&D",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )
    stage = project.stages.get(stage_code="D1")
    return Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code="D1-RD",
        name="RD work",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=rd,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )


@pytest.mark.django_db
def test_only_matching_department_head_may_assign(
    rd_task: Task,
    qa_head: User,
    organization: Organization,
) -> None:
    other = User.objects.create_user(
        organization=organization,
        display_name="QA Worker",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=qa_head.primary_department,
    )
    with pytest.raises(PermissionDeniedError):
        AssignTaskResponsible(
            context=CommandContext.for_actor(qa_head),
            task_public_id=rd_task.public_id,
            user_public_id=other.public_id,
            version_no=1,
        ).execute()


@pytest.mark.django_db
def test_responsible_user_can_update_own_task(
    project: Project,
    organization: Organization,
    grant_action,
) -> None:
    dept = Department.objects.create(
        organization=organization,
        department_code="OWN",
        name="Own Dept",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )
    head = User.objects.create_user(
        organization=organization,
        display_name="Own Head",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    worker = User.objects.create_user(
        organization=organization,
        display_name="Own Worker",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    grant_action(head, "task.assign_department_member", "task", role_code="DEPARTMENT_HEAD")
    task = Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-OWN",
        name="Own task",
        source_type="TEMPLATE",
        is_core=False,
        responsible_department=dept,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )
    AssignTaskResponsible(
        context=CommandContext.for_actor(head),
        task_public_id=task.public_id,
        user_public_id=worker.public_id,
        version_no=1,
    ).execute()
    updated = TransitionTask(
        context=CommandContext.for_actor(worker),
        task_public_id=task.public_id,
        target_status=TaskStatus.IN_PROGRESS,
        version_no=2,
    ).execute()
    assert updated.status == TaskStatus.IN_PROGRESS


@pytest.mark.django_db
def test_non_responsible_cannot_update_task(
    project: Project,
    organization: Organization,
    grant_action,
) -> None:
    dept = Department.objects.create(
        organization=organization,
        department_code="NOPE",
        name="Nope",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )
    head = User.objects.create_user(
        organization=organization,
        display_name="Nope Head",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    worker = User.objects.create_user(
        organization=organization,
        display_name="Assigned",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    stranger = User.objects.create_user(
        organization=organization,
        display_name="Stranger",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=dept,
    )
    grant_action(head, "task.assign_department_member", "task", role_code="DEPARTMENT_HEAD")
    task = Task.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        task_code="D1-NOPE",
        name="Guarded",
        source_type="TEMPLATE",
        is_core=False,
        responsible_department=dept,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )
    AssignTaskResponsible(
        context=CommandContext.for_actor(head),
        task_public_id=task.public_id,
        user_public_id=worker.public_id,
        version_no=1,
    ).execute()
    with pytest.raises(PermissionDeniedError):
        TransitionTask(
            context=CommandContext.for_actor(stranger),
            task_public_id=task.public_id,
            target_status=TaskStatus.IN_PROGRESS,
            version_no=2,
        ).execute()
