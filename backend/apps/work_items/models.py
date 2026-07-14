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


class DeliverableTier(models.TextChoices):
    CORE_REQUIRED = "CORE_REQUIRED", "Core required"
    TEMPLATE_RECOMMENDED = "TEMPLATE_RECOMMENDED", "Template recommended"
    PROJECT_CUSTOM = "PROJECT_CUSTOM", "Project custom"


class DeliverableStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CONTROLLED = "CONTROLLED", "Controlled"
    EXEMPTED = "EXEMPTED", "Exempted"
    VOIDED = "VOIDED", "Voided"


class DeliverableRevisionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    LOCKED = "LOCKED", "Locked"
    CONTROLLED = "CONTROLLED", "Controlled"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class ProfessionalConfirmationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    RETURNED = "RETURNED", "Returned"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class Deliverable(OrganizationOwnedModel):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="deliverables",
    )
    stage = models.ForeignKey(
        "projects.ProjectStage",
        on_delete=models.PROTECT,
        related_name="deliverables",
    )
    deliverable_code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    tier = models.CharField(max_length=32, choices=DeliverableTier.choices)
    status = models.CharField(
        max_length=32,
        choices=DeliverableStatus.choices,
        default=DeliverableStatus.NOT_STARTED,
    )
    compiler_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="compiled_deliverables",
    )
    requires_professional_confirmation = models.BooleanField(default=True)
    current_revision = models.ForeignKey(
        "work_items.DeliverableRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    planned_due_at = models.DateTimeField(null=True, blank=True)
    exemption_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "work_items_deliverable"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "deliverable_code"],
                name="work_items_deliverable_project_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["stage", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.deliverable_code}"


class DeliverableRevision(OrganizationOwnedModel):
    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    revision_number = models.PositiveIntegerField()
    document_version = models.ForeignKey(
        "documents.DocumentVersion",
        on_delete=models.PROTECT,
        related_name="deliverable_revisions",
    )
    status = models.CharField(
        max_length=32,
        choices=DeliverableRevisionStatus.choices,
        default=DeliverableRevisionStatus.DRAFT,
    )
    content_hash = models.CharField(max_length=64)
    submitted_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="submitted_deliverable_revisions",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "work_items_deliverable_revision"
        constraints = [
            models.UniqueConstraint(
                fields=["deliverable", "revision_number"],
                name="work_items_deliverable_revision_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.deliverable_id}:r{self.revision_number}"


class ProfessionalConfirmation(OrganizationOwnedModel):
    deliverable_revision = models.ForeignKey(
        DeliverableRevision,
        on_delete=models.PROTECT,
        related_name="confirmations",
    )
    confirmer = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="professional_confirmations",
    )
    assigned_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="assigned_professional_confirmations",
    )
    status = models.CharField(
        max_length=32,
        choices=ProfessionalConfirmationStatus.choices,
        default=ProfessionalConfirmationStatus.PENDING,
    )
    comment = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "work_items_professional_confirmation"
        indexes = [
            models.Index(fields=["deliverable_revision", "status"]),
            models.Index(fields=["confirmer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.deliverable_revision_id}:{self.status}"
