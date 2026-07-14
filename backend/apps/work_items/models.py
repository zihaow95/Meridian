"""Project tasks and dependency edges."""

from __future__ import annotations

from django.db import models

from apps.identity.models.user import UserStatus
from apps.platform.models.base import OrganizationOwnedModel


class TaskSourceType(models.TextChoices):
    TEMPLATE = "TEMPLATE", "Template"
    PROJECT_CUSTOM = "PROJECT_CUSTOM", "Project custom"


class TaskStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    BLOCKED = "BLOCKED", "Blocked"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class TaskDependencyType(models.TextChoices):
    HARD = "HARD", "Hard"
    SOFT = "SOFT", "Soft"


class Task(OrganizationOwnedModel):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    stage = models.ForeignKey(
        "projects.ProjectStage",
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    task_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    source_type = models.CharField(
        max_length=32,
        choices=TaskSourceType.choices,
        default=TaskSourceType.TEMPLATE,
    )
    is_core = models.BooleanField(default=True)
    responsible_user = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="responsible_tasks",
    )
    responsible_department = models.ForeignKey(
        "identity.Department",
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    status = models.CharField(
        max_length=32,
        choices=TaskStatus.choices,
        default=TaskStatus.NOT_STARTED,
    )
    planned_start_at = models.DateTimeField(null=True, blank=True)
    planned_due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    block_reason = models.CharField(max_length=255, blank=True, default="")
    version_no = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "work_items_task"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "task_code"],
                name="work_items_task_project_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["responsible_user", "status"]),
            models.Index(fields=["stage", "status"]),
        ]

    @property
    def derived_assignment_state(self) -> str:
        if self.responsible_user_id is None:
            return "UNASSIGNED"
        responsible = self.responsible_user
        if responsible is None or responsible.status != UserStatus.ACTIVE:
            return "UNASSIGNED_REQUIRED"
        return "ASSIGNED"

    def __str__(self) -> str:
        return f"{self.project_id}:{self.task_code}"


class TaskDependency(OrganizationOwnedModel):
    task = models.ForeignKey(
        Task,
        on_delete=models.PROTECT,
        related_name="dependencies",
    )
    predecessor = models.ForeignKey(
        Task,
        on_delete=models.PROTECT,
        related_name="dependents",
    )
    dependency_type = models.CharField(
        max_length=16,
        choices=TaskDependencyType.choices,
        default=TaskDependencyType.HARD,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "work_items_task_dependency"
        constraints = [
            models.UniqueConstraint(
                fields=["task", "predecessor"],
                name="work_items_task_dependency_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.predecessor_id}->{self.task_id}"
