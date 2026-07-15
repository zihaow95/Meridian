"""Task responsibility, dependency DAG, and status rules (EXE-003/004)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.work_items.errors import (
    CoreTaskCannotCancel,
    HardDependencyBlocksStart,
    TaskDependencyCycle,
    TaskVersionConflict,
)
from apps.work_items.models import Task, TaskDependencyType, TaskStatus
from apps.work_items.services.manage_tasks import (
    AddTaskDependency,
    AssignTaskResponsible,
    TransitionTask,
)


@pytest.fixture
def rd_department(organization: Organization) -> Department:
    department, _ = Department.objects.get_or_create(
        organization=organization,
        department_code="RD",
        defaults={
            "name": "R&D",
            "status": DepartmentStatus.ACTIVE,
            "valid_from": timezone.now(),
        },
    )
    return department


@pytest.fixture
def dept_head(
    organization: Organization,
    rd_department: Department,
    grant_action,
) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="RD Head",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=rd_department,
    )
    grant_action(
        user,
        "task.assign_department_member",
        "task",
        role_code="DEPARTMENT_HEAD",
    )
    grant_action(user, "task.update_own", "task", role_code="DEPARTMENT_HEAD")
    grant_action(user, "plan.edit", "project", role_code="DEPARTMENT_HEAD")
    return user


@pytest.fixture
def worker(
    organization: Organization,
    rd_department: Department,
) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Worker",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
        primary_department=rd_department,
    )


@pytest.fixture
def core_task(project: Project, rd_department: Department) -> Task:
    stage = project.stages.get(stage_code="D1")
    return Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code="D1-CORE",
        name="Core definition",
        source_type="TEMPLATE",
        is_core=True,
        responsible_department=rd_department,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )


@pytest.fixture
def optional_task(project: Project, rd_department: Department) -> Task:
    stage = project.stages.get(stage_code="D1")
    return Task.objects.create(
        organization=project.organization,
        project=project,
        stage=stage,
        task_code="D1-OPT",
        name="Optional analysis",
        source_type="PROJECT_CUSTOM",
        is_core=False,
        responsible_department=rd_department,
        status=TaskStatus.NOT_STARTED,
        version_no=1,
    )


@pytest.mark.django_db
def test_assign_sets_single_responsible(
    core_task: Task,
    dept_head: User,
    worker: User,
) -> None:
    updated = AssignTaskResponsible(
        context=CommandContext.for_actor(dept_head),
        task_public_id=core_task.public_id,
        user_public_id=worker.public_id,
        version_no=1,
    ).execute()
    assert updated.responsible_user_id == worker.id
    assert updated.version_no == 2
    assert Task.objects.filter(pk=core_task.pk, responsible_user=worker).count() == 1


@pytest.mark.django_db
def test_project_leader_cannot_force_cross_department_assignment(
    core_task: Task,
    project: Project,
    worker: User,
) -> None:
    leader = project.leader
    with pytest.raises(PermissionDeniedError):
        AssignTaskResponsible(
            context=CommandContext.for_actor(leader),
            task_public_id=core_task.public_id,
            user_public_id=worker.public_id,
            version_no=1,
        ).execute()
    core_task.refresh_from_db()
    assert core_task.responsible_user_id is None


@pytest.mark.django_db
def test_disabled_responsible_derives_unassigned_required(
    core_task: Task,
    dept_head: User,
    worker: User,
) -> None:
    AssignTaskResponsible(
        context=CommandContext.for_actor(dept_head),
        task_public_id=core_task.public_id,
        user_public_id=worker.public_id,
        version_no=1,
    ).execute()
    worker.status = UserStatus.DISABLED
    worker.disabled_at = timezone.now()
    worker.save(update_fields=["status", "disabled_at", "updated_at"])
    core_task.refresh_from_db()
    assert core_task.derived_assignment_state == "UNASSIGNED_REQUIRED"


@pytest.mark.django_db
def test_hard_dependency_blocks_start(
    core_task: Task,
    optional_task: Task,
    dept_head: User,
) -> None:
    AddTaskDependency(
        context=CommandContext.for_actor(dept_head),
        task_public_id=optional_task.public_id,
        predecessor_public_id=core_task.public_id,
        dependency_type=TaskDependencyType.HARD,
        version_no=1,
    ).execute()
    with pytest.raises(HardDependencyBlocksStart):
        TransitionTask(
            context=CommandContext.for_actor(dept_head),
            task_public_id=optional_task.public_id,
            target_status=TaskStatus.IN_PROGRESS,
            version_no=2,
        ).execute()


@pytest.mark.django_db
def test_dependency_cycle_rejected(
    core_task: Task,
    optional_task: Task,
    dept_head: User,
) -> None:
    AddTaskDependency(
        context=CommandContext.for_actor(dept_head),
        task_public_id=optional_task.public_id,
        predecessor_public_id=core_task.public_id,
        dependency_type=TaskDependencyType.HARD,
        version_no=1,
    ).execute()
    with pytest.raises(TaskDependencyCycle):
        AddTaskDependency(
            context=CommandContext.for_actor(dept_head),
            task_public_id=core_task.public_id,
            predecessor_public_id=optional_task.public_id,
            dependency_type=TaskDependencyType.HARD,
            version_no=1,
        ).execute()


@pytest.mark.django_db
def test_core_task_cannot_cancel(
    core_task: Task,
    dept_head: User,
) -> None:
    with pytest.raises(CoreTaskCannotCancel):
        TransitionTask(
            context=CommandContext.for_actor(dept_head),
            task_public_id=core_task.public_id,
            target_status=TaskStatus.CANCELLED,
            version_no=1,
        ).execute()


@pytest.mark.django_db
def test_stale_version_conflicts(
    core_task: Task,
    dept_head: User,
    worker: User,
) -> None:
    AssignTaskResponsible(
        context=CommandContext.for_actor(dept_head),
        task_public_id=core_task.public_id,
        user_public_id=worker.public_id,
        version_no=1,
    ).execute()
    with pytest.raises(TaskVersionConflict):
        AssignTaskResponsible(
            context=CommandContext.for_actor(dept_head),
            task_public_id=core_task.public_id,
            user_public_id=worker.public_id,
            version_no=1,
        ).execute()
