"""Minimal project instance models for phase 2 project creation."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class ProjectType(models.TextChoices):
    NEW_PRODUCT = "NEW_PRODUCT", "New product"
    PRODUCT_CHANGE = "PRODUCT_CHANGE", "Product change"


class ProjectStatus(models.TextChoices):
    INITIALIZING = "INITIALIZING", "Initializing"
    ACTIVE = "ACTIVE", "Active"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    PUBLISH_PENDING_REPAIR = "PUBLISH_PENDING_REPAIR", "Publish pending repair"
    OPERATING = "OPERATING", "Operating"
    CLOSED = "CLOSED", "Closed"


class ProjectStageStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    ACTIVE = "ACTIVE", "Active"
    READY_FOR_GATE = "READY_FOR_GATE", "Ready for gate"
    COMPLETED = "COMPLETED", "Completed"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    MIGRATED_HISTORY = "MIGRATED_HISTORY", "Migrated history"


class StageHandlingMode(models.TextChoices):
    EXECUTE = "EXECUTE", "Execute"
    REUSE = "REUSE", "Reuse"
    SIMPLIFY = "SIMPLIFY", "Simplify"
    EXEMPT = "EXEMPT", "Exempt"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
    PARALLEL = "PARALLEL", "Parallel"


class ProjectRole(models.TextChoices):
    LEADER = "LEADER", "Leader"
    DEPUTY = "DEPUTY", "Deputy"
    MEMBER = "MEMBER", "Member"


class Project(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    project_type = models.CharField(max_length=24, choices=ProjectType.choices)
    status = models.CharField(
        max_length=32,
        choices=ProjectStatus.choices,
        default=ProjectStatus.INITIALIZING,
    )
    candidate = models.OneToOneField(
        "opportunities.ProjectCandidate",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="project",
    )
    leader = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="led_projects",
    )
    deputy_leader = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deputy_led_projects",
    )
    product_asset = models.ForeignKey(
        "products.ProductAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    product_draft = models.ForeignKey(
        "products.ProductChangeSet",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    template_snapshot = models.ForeignKey(
        "configuration.ConfigurationSnapshot",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    current_stage = models.ForeignKey(
        "projects.ProjectStage",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    migration_baseline = models.OneToOneField(
        "projects.MigrationBaseline",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="project",
    )
    planned_start_at = models.DateTimeField(null=True, blank=True)
    planned_end_at = models.DateTimeField(null=True, blank=True)
    actual_start_at = models.DateTimeField(null=True, blank=True)
    actual_end_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_project"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="projects_project_org_no_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "updated_at"]),
            models.Index(fields=["organization", "status", "current_stage"]),
            models.Index(fields=["leader", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.name}"


class ProjectTemplateSnapshot(OrganizationOwnedModel):
    """Project-owned pointer to an immutable configuration snapshot."""

    project = models.OneToOneField(
        Project,
        on_delete=models.PROTECT,
        related_name="project_template_snapshot",
    )
    configuration_snapshot = models.ForeignKey(
        "configuration.ConfigurationSnapshot",
        on_delete=models.PROTECT,
        related_name="project_template_snapshots",
    )
    source_version = models.ForeignKey(
        "configuration.ConfigurationVersion",
        on_delete=models.PROTECT,
        related_name="project_template_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "projects_project_template_snapshot"

    def __str__(self) -> str:
        return f"template-snapshot:{self.project_id}"


class ProjectStage(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="stages",
    )
    stage_code = models.CharField(max_length=16)
    name = models.CharField(max_length=200)
    sequence_no = models.PositiveIntegerField()
    status = models.CharField(
        max_length=32,
        choices=ProjectStageStatus.choices,
        default=ProjectStageStatus.NOT_STARTED,
    )
    handling_mode = models.CharField(
        max_length=32,
        choices=StageHandlingMode.choices,
        default=StageHandlingMode.EXECUTE,
    )
    gate_code = models.CharField(max_length=64, blank=True, default="")
    gate_type = models.CharField(max_length=16, blank=True, default="")
    depends_on = models.JSONField(default=list)
    planned_start_at = models.DateTimeField(null=True, blank=True)
    planned_end_at = models.DateTimeField(null=True, blank=True)
    actual_start_at = models.DateTimeField(null=True, blank=True)
    actual_end_at = models.DateTimeField(null=True, blank=True)
    exception = models.ForeignKey(
        "projects.ExecutionException",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_project_stage"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "stage_code"],
                name="projects_project_stage_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "sequence_no"]),
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.stage_code}"


class ExecutionExceptionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class ExecutionException(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="execution_exceptions",
    )
    stage = models.ForeignKey(
        ProjectStage,
        on_delete=models.PROTECT,
        related_name="execution_exceptions",
    )
    exception_type = models.CharField(max_length=32, choices=StageHandlingMode.choices)
    previous_mode = models.CharField(max_length=32, choices=StageHandlingMode.choices)
    requested_mode = models.CharField(max_length=32, choices=StageHandlingMode.choices)
    rationale = models.TextField()
    evidence_summary = models.JSONField(default=dict)
    requested_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="requested_execution_exceptions",
    )
    confirmed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_execution_exceptions",
    )
    status = models.CharField(
        max_length=32,
        choices=ExecutionExceptionStatus.choices,
        default=ExecutionExceptionStatus.PENDING,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_execution_exception"
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["stage", "status"]),
        ]


class PlanChangeType(models.TextChoices):
    MINOR = "MINOR", "Minor"
    IMPORTANT = "IMPORTANT", "Important"
    RESOURCE_ESCALATION = "RESOURCE_ESCALATION", "Resource escalation"


class PlanChangeStatus(models.TextChoices):
    APPLIED = "APPLIED", "Applied"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION", "Pending confirmation"
    CONFIRMED = "CONFIRMED", "Confirmed"
    REJECTED = "REJECTED", "Rejected"


class PlanChange(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="plan_changes",
    )
    change_type = models.CharField(max_length=32, choices=PlanChangeType.choices)
    target_type = models.CharField(max_length=64)
    target_public_id = models.UUIDField()
    field_name = models.CharField(max_length=64)
    before_value = models.TextField(blank=True, default="")
    after_value = models.TextField(blank=True, default="")
    impact_summary = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="requested_plan_changes",
    )
    confirmed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_plan_changes",
    )
    status = models.CharField(
        max_length=32,
        choices=PlanChangeStatus.choices,
        default=PlanChangeStatus.PENDING_CONFIRMATION,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "projects_plan_change"
        indexes = [
            models.Index(fields=["project", "status"]),
        ]


class EmergencyExecutionStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    COMPLETED = "COMPLETED", "Completed"
    OVERDUE = "OVERDUE", "Overdue"


class EmergencyExecution(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="emergency_executions",
    )
    subject_summary = models.CharField(max_length=255)
    pending_confirmation = models.TextField()
    confirmation_evidence = models.TextField(blank=True, default="")
    started_at = models.DateTimeField()
    due_at = models.DateTimeField()
    initiated_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="initiated_emergency_executions",
    )
    initiator_roles_snapshot = models.JSONField(default=list)
    status = models.CharField(
        max_length=32,
        choices=EmergencyExecutionStatus.choices,
        default=EmergencyExecutionStatus.OPEN,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_emergency_execution"
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["due_at", "status"]),
        ]


class ProjectMember(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="members",
    )
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="project_memberships",
    )
    project_role = models.CharField(max_length=16, choices=ProjectRole.choices)
    # MySQL cannot enforce partial unique indexes; set only for active memberships.
    active_role_key = models.CharField(max_length=96, null=True, blank=True, unique=True)
    active_from = models.DateTimeField()
    active_to = models.DateTimeField(null=True, blank=True)
    appointed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="project_appointments",
    )

    class Meta:
        db_table = "projects_project_member"
        indexes = [
            models.Index(fields=["project", "project_role"]),
            models.Index(fields=["user", "active_from"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.user_id}:{self.project_role}"


class ProjectOpportunitySource(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="opportunity_sources",
    )
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="project_sources",
    )
    source_role = models.CharField(max_length=16)
    linked_at = models.DateTimeField()

    class Meta:
        db_table = "projects_project_opportunity_source"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "opportunity"],
                name="projects_opportunity_source_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "linked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.opportunity_id}"


class MigrationBatchStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class MigrationDisposition(models.TextChoices):
    CONTINUE = "CONTINUE", "Continue"
    ARCHIVE_ONLY = "ARCHIVE_ONLY", "Archive only"


class MigrationBaselineStatus(models.TextChoices):
    IMPORTED = "IMPORTED", "Imported"
    CONFIRMED = "CONFIRMED", "Confirmed"
    FAILED = "FAILED", "Failed"


class MigrationBatch(OrganizationOwnedModel):
    batch_key = models.CharField(max_length=128)
    imported_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="imported_migration_batches",
    )
    status = models.CharField(
        max_length=16,
        choices=MigrationBatchStatus.choices,
        default=MigrationBatchStatus.OPEN,
    )
    source_row_count = models.PositiveIntegerField(default=0)
    accepted_row_count = models.PositiveIntegerField(default=0)
    error_row_count = models.PositiveIntegerField(default=0)
    row_errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_migration_batch"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "batch_key"],
                name="projects_migration_batch_org_key_uniq",
            ),
        ]


class MigrationBaseline(OrganizationOwnedModel):
    batch = models.ForeignKey(
        MigrationBatch,
        on_delete=models.PROTECT,
        related_name="baselines",
    )
    external_project_id = models.CharField(max_length=128)
    name = models.CharField(max_length=200)
    current_stage_code = models.CharField(max_length=32)
    leader_display_name = models.CharField(max_length=128, blank=True, default="")
    disposition = models.CharField(
        max_length=32,
        choices=MigrationDisposition.choices,
        default=MigrationDisposition.CONTINUE,
    )
    history_decision_summary = models.TextField(blank=True, default="")
    plan_summary = models.JSONField(default=dict)
    history_tasks = models.JSONField(default=list)
    history_files = models.JSONField(default=list)
    history_deliverables = models.JSONField(default=list)
    status = models.CharField(
        max_length=16,
        choices=MigrationBaselineStatus.choices,
        default=MigrationBaselineStatus.IMPORTED,
    )
    confirmed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="confirmed_migration_baselines",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_idempotency_key = models.CharField(max_length=128, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_migration_baseline"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "external_project_id"],
                name="projects_migration_baseline_batch_external_uniq",
            ),
            models.UniqueConstraint(
                fields=["organization", "external_project_id"],
                name="projects_migration_baseline_org_external_uniq",
            ),
        ]
