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


class MaterialType(models.TextChoices):
    PROPOSAL_VERSION = "PROPOSAL_VERSION", "Proposal version"
    CASE_ASSESSMENT = "CASE_ASSESSMENT", "Case assessment"


class GateStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    DECIDED = "DECIDED", "Decided"
    CANCELLED = "CANCELLED", "Cancelled"


class StageGateInstance(OrganizationOwnedModel):
    subject_type = models.CharField(max_length=32, choices=SubjectType.choices)
    subject_public_id = models.UUIDField()
    stage_code = models.CharField(max_length=32, choices=StageCode.choices)
    cycle_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=GateStatus.choices,
        default=GateStatus.OPEN,
    )
    primary_material_type = models.CharField(max_length=32, choices=MaterialType.choices)
    primary_material_public_id = models.UUIDField()
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
            models.UniqueConstraint(
                fields=["primary_material_type", "primary_material_public_id"],
                condition=models.Q(status="OPEN"),
                name="stage_gates_active_material_uniq",
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
