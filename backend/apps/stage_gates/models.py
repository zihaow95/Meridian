"""Major stage gate instances and immutable decisions.

Result and stage codes are fixed by the system master TRD; no domain may mint a
parallel set of values for the same meaning.
"""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class GateResult(models.TextChoices):
    APPROVED = "APPROVED", "Approved"
    APPROVED_WITH_EXCEPTION = "APPROVED_WITH_EXCEPTION", "Approved with exception"
    NEEDS_INFO = "NEEDS_INFO", "Needs info"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"


class StageCode(models.TextChoices):
    PROPOSAL_TO_CASE = "PROPOSAL_TO_CASE", "Proposal to case"
    CASE_TO_PROJECT = "CASE_TO_PROJECT", "Case to project"
    FIRST_LAUNCH = "FIRST_LAUNCH", "First launch"
    PRODUCT_RETIREMENT = "PRODUCT_RETIREMENT", "Product retirement"


class SubjectType(models.TextChoices):
    OPPORTUNITY = "OPPORTUNITY", "Opportunity"
    PROJECT_CANDIDATE = "PROJECT_CANDIDATE", "Project candidate"
    PROJECT = "PROJECT", "Project"


class MaterialType(models.TextChoices):
    PROPOSAL_VERSION = "PROPOSAL_VERSION", "Proposal version"
    CASE_ASSESSMENT = "CASE_ASSESSMENT", "Case assessment"
    PROJECT_STAGE = "PROJECT_STAGE", "Project stage"
    DELIVERABLE_REVISION = "DELIVERABLE_REVISION", "Deliverable revision"
    DOCUMENT_VERSION = "DOCUMENT_VERSION", "Document version"


class GateStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    READY = "READY", "Ready"
    SUBMITTED = "SUBMITTED", "Submitted"
    NEEDS_INFO = "NEEDS_INFO", "Needs info"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    APPROVED = "APPROVED", "Approved"
    DECIDED = "DECIDED", "Decided"
    CANCELLED = "CANCELLED", "Cancelled"


class GateType(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    MAJOR = "MAJOR", "Major"


class StageGateInstance(OrganizationOwnedModel):
    subject_type = models.CharField(max_length=32, choices=SubjectType.choices)
    subject_public_id = models.UUIDField()
    stage_code = models.CharField(max_length=64)
    cycle_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=GateStatus.choices,
        default=GateStatus.OPEN,
    )
    gate_type = models.CharField(
        max_length=16,
        choices=GateType.choices,
        default=GateType.MAJOR,
    )
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stage_gates",
    )
    project_stage = models.ForeignKey(
        "projects.ProjectStage",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stage_gates",
    )
    primary_material_type = models.CharField(max_length=32, choices=MaterialType.choices)
    primary_material_public_id = models.UUIDField()
    # MySQL cannot enforce partial unique indexes; this is set only while status=OPEN.
    open_material_key = models.CharField(max_length=96, null=True, blank=True, unique=True)
    current_submission = models.ForeignKey(
        "stage_gates.GateSubmission",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    previous_cycle = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="next_cycles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stage_gates_instance"
        constraints = [
            models.UniqueConstraint(
                fields=["subject_type", "subject_public_id", "stage_code", "cycle_number"],
                name="stage_gates_instance_cycle_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["subject_type", "subject_public_id", "stage_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.stage_code}:{self.subject_public_id}:c{self.cycle_number}"


class GateMaterialReference(OrganizationOwnedModel):
    stage_gate = models.ForeignKey(
        StageGateInstance,
        on_delete=models.PROTECT,
        related_name="material_references",
    )
    material_type = models.CharField(max_length=32, choices=MaterialType.choices)
    material_public_id = models.UUIDField()
    locked_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_gates_material_reference"
        constraints = [
            models.UniqueConstraint(
                fields=["stage_gate", "material_type", "material_public_id"],
                name="stage_gates_material_ref_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.stage_gate_id}:{self.material_type}"


class GateSubmission(OrganizationOwnedModel):
    stage_gate = models.ForeignKey(
        StageGateInstance,
        on_delete=models.PROTECT,
        related_name="submissions",
    )
    submission_number = models.PositiveIntegerField()
    snapshot_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    validation_result_json = models.JSONField(default=dict)
    submitted_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="gate_submissions",
    )
    submitted_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_gates_gate_submission"
        constraints = [
            models.UniqueConstraint(
                fields=["stage_gate", "submission_number"],
                name="stage_gates_submission_number_uniq",
            ),
            models.UniqueConstraint(
                fields=["stage_gate", "idempotency_key"],
                name="stage_gates_submission_idempotency_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.stage_gate_id}:s{self.submission_number}"


class GateSubmissionMaterialReference(OrganizationOwnedModel):
    submission = models.ForeignKey(
        GateSubmission,
        on_delete=models.PROTECT,
        related_name="material_references",
    )
    material_type = models.CharField(max_length=32, choices=MaterialType.choices)
    material_public_id = models.UUIDField()
    content_hash = models.CharField(max_length=64, blank=True, default="")
    locked_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_gates_submission_material_reference"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "material_type", "material_public_id"],
                name="stage_gates_submission_material_uniq",
            ),
        ]


class GateDecision(OrganizationOwnedModel):
    """One decision per submission so NEEDS_INFO can reopen a later cycle."""

    stage_gate = models.ForeignKey(
        StageGateInstance,
        on_delete=models.PROTECT,
        related_name="normal_decisions",
    )
    submission = models.OneToOneField(
        GateSubmission,
        on_delete=models.PROTECT,
        related_name="decision",
    )
    result = models.CharField(max_length=32, choices=GateResult.choices)
    decided_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="normal_gate_decisions",
    )
    decision_summary = models.TextField(blank=True, default="")
    exception_rationale = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True)
    decided_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_gates_gate_decision"

    def __str__(self) -> str:
        return f"{self.stage_gate_id}:{self.result}"


class MajorGateDecision(OrganizationOwnedModel):
    stage_gate = models.OneToOneField(
        StageGateInstance,
        on_delete=models.PROTECT,
        related_name="decision",
    )
    management_conclusion = models.CharField(max_length=32, choices=GateResult.choices)
    management_conclusion_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gate_management_conclusions",
    )
    final_decision = models.CharField(max_length=32, choices=GateResult.choices)
    final_decision_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="gate_final_decisions",
    )
    has_conclusion_difference = models.BooleanField(default=False)
    decision_summary = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=128)
    decided_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stage_gates_major_decision"

    def __str__(self) -> str:
        return f"{self.stage_gate_id}:{self.final_decision}"
