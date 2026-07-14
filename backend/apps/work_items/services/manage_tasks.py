"""Task assignment, transition, and dependency commands."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.work_items.errors import (
    CoreTaskCannotCancel,
    HardDependencyBlocksStart,
    TaskDependencyCycle,
    TaskNotFound,
    TaskVersionConflict,
)
from apps.work_items.models import Task, TaskDependency, TaskDependencyType, TaskStatus


def _authorize_task(*, actor: User, task: Task, action: str) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="task",
            public_id=task.public_id,
            organization_id=task.organization_id,
            scope_department_ids=frozenset({task.responsible_department_id}),
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


@dataclass
class AssignTaskResponsible:
    context: CommandContext
    task_public_id: UUID
    user_public_id: UUID
    version_no: int

    def execute(self) -> Task:
        actor = self.context.actor
        with transaction.atomic():
            task = (
                Task.objects.select_for_update()
                .select_related("responsible_department", "project")
                .filter(
                    public_id=self.task_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if task is None:
                raise PermissionDeniedError()
            _authorize_task(actor=actor, task=task, action="task.assign_department_member")
            if actor.primary_department_id != task.responsible_department_id:
                raise PermissionDeniedError()
            if task.version_no != self.version_no:
                raise TaskVersionConflict()

            assignee = User.objects.filter(
                public_id=self.user_public_id,
                organization_id=actor.organization_id,
            ).first()
            if assignee is None or assignee.status != UserStatus.ACTIVE:
                raise PermissionDeniedError()
            if assignee.primary_department_id != task.responsible_department_id:
                raise PermissionDeniedError()

            task.responsible_user = assignee
            task.version_no += 1
            task.save(update_fields=["responsible_user", "version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="task.assign_department_member",
                    resource_type="task",
                    resource_public_id=task.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"responsible_user_public_id": str(assignee.public_id)},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="task.assigned",
                    aggregate_type="task",
                    aggregate_id=task.public_id,
                    payload={
                        "task_public_id": str(task.public_id),
                        "responsible_user_public_id": str(assignee.public_id),
                    },
                    occurred_at=self.context.occurred_at,
                )
            )
            return task


@dataclass
class TransitionTask:
    context: CommandContext
    task_public_id: UUID
    target_status: str
    version_no: int

    def execute(self) -> Task:
        actor = self.context.actor
        with transaction.atomic():
            task = (
                Task.objects.select_for_update()
                .select_related("responsible_user", "responsible_department")
                .filter(
                    public_id=self.task_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if task is None:
                raise PermissionDeniedError()
            _authorize_task(actor=actor, task=task, action="task.update_own")
            if task.version_no != self.version_no:
                raise TaskVersionConflict()

            target = TaskStatus(self.target_status)
            if target == TaskStatus.CANCELLED and task.is_core:
                raise CoreTaskCannotCancel()
            if target == TaskStatus.IN_PROGRESS:
                blockers = TaskDependency.objects.filter(
                    task=task,
                    dependency_type=TaskDependencyType.HARD,
                ).exclude(predecessor__status=TaskStatus.COMPLETED)
                if blockers.exists():
                    raise HardDependencyBlocksStart()

            task.status = target
            update_fields = ["status", "version_no", "updated_at"]
            if target == TaskStatus.COMPLETED:
                task.completed_at = self.context.occurred_at
                update_fields.append("completed_at")
            task.version_no += 1
            task.save(update_fields=update_fields)

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="task.update_own",
                    resource_type="task",
                    resource_public_id=task.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"status": task.status},
                )
            )
            if target == TaskStatus.COMPLETED:
                register_outbox_event(
                    OutboxMessage(
                        event_type="task.completed",
                        aggregate_type="task",
                        aggregate_id=task.public_id,
                        payload={"task_public_id": str(task.public_id)},
                        occurred_at=self.context.occurred_at,
                    )
                )
            return task


@dataclass
class AddTaskDependency:
    context: CommandContext
    task_public_id: UUID
    predecessor_public_id: UUID
    dependency_type: str
    version_no: int

    def execute(self) -> Task:
        actor = self.context.actor
        with transaction.atomic():
            task = (
                Task.objects.select_for_update()
                .select_related("project", "responsible_department")
                .filter(
                    public_id=self.task_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if task is None:
                raise PermissionDeniedError()
            predecessor = Task.objects.filter(
                public_id=self.predecessor_public_id,
                project_id=task.project_id,
                organization_id=actor.organization_id,
            ).first()
            if predecessor is None:
                raise TaskNotFound()

            decision = authorize(
                subject_for(actor),
                action="plan.edit",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=task.project.public_id,
                    organization_id=task.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()
            if task.version_no != self.version_no:
                raise TaskVersionConflict()
            if _creates_cycle(task=task, predecessor=predecessor):
                raise TaskDependencyCycle()

            TaskDependency.objects.create(
                organization=task.organization,
                task=task,
                predecessor=predecessor,
                dependency_type=self.dependency_type,
            )
            task.version_no += 1
            task.save(update_fields=["version_no", "updated_at"])
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="plan.edit",
                    resource_type="task",
                    resource_public_id=task.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "predecessor_public_id": str(predecessor.public_id),
                        "dependency_type": self.dependency_type,
                    },
                )
            )
            return task


def _creates_cycle(*, task: Task, predecessor: Task) -> bool:
    if task.pk == predecessor.pk:
        return True
    stack = [task.pk]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current == predecessor.pk:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(
            TaskDependency.objects.filter(predecessor_id=current).values_list(
                "task_id", flat=True
            )
        )
    return False
