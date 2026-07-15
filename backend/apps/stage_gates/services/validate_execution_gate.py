"""Validate execution gate readiness and collect structured blockers."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.models import StorageStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import (
    EmergencyExecution,
    EmergencyExecutionStatus,
    ExecutionException,
    ExecutionExceptionStatus,
)
from apps.stage_gates.models import StageGateInstance
from apps.work_items.models import (
    Deliverable,
    DeliverableRevision,
    DeliverableStatus,
    DeliverableTier,
    ProfessionalConfirmation,
    ProfessionalConfirmationStatus,
    Task,
    TaskDependency,
    TaskDependencyType,
    TaskStatus,
)


@dataclass(frozen=True)
class GateValidationResult:
    blocks: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return not self.blocks


@dataclass
class ValidateExecutionGate:
    context: CommandContext
    stage_gate_public_id: UUID

    def execute(self) -> GateValidationResult:
        actor = self.context.actor
        gate = (
            StageGateInstance.objects.select_related("project", "project_stage")
            .filter(
                public_id=self.stage_gate_public_id,
                organization_id=actor.organization_id,
            )
            .first()
        )
        if gate is None or gate.project_id is None:
            raise PermissionDeniedError()
        decision = authorize(
            subject_for(actor),
            action="stage_gate.submit",
            resource=ResourceDescriptor(
                resource_type="stage_gate",
                public_id=gate.public_id,
                organization_id=gate.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

        return collect_execution_gate_validation(gate)


def collect_execution_gate_validation(gate: StageGateInstance) -> GateValidationResult:
    blocks: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    project = gate.project
    stage = gate.project_stage
    if project is None or stage is None:
        blocks.append({"code": "GATE_CONTEXT_MISSING", "message": "Project stage is required."})
        return GateValidationResult(blocks=blocks, warnings=warnings)

    incomplete_core = Task.objects.filter(
        project=project,
        stage=stage,
        is_core=True,
    ).exclude(status=TaskStatus.COMPLETED)
    if incomplete_core.exists():
        blocks.append(
            {
                "code": "CORE_TASK_INCOMPLETE",
                "message": "One or more core tasks are incomplete.",
            }
        )

    hard_open = TaskDependency.objects.filter(
        task__project=project,
        task__stage=stage,
        dependency_type=TaskDependencyType.HARD,
    ).exclude(predecessor__status=TaskStatus.COMPLETED)
    if hard_open.exists():
        blocks.append(
            {
                "code": "HARD_DEPENDENCY_INCOMPLETE",
                "message": "Hard task dependencies are incomplete.",
            }
        )

    core_deliverables = Deliverable.objects.filter(
        project=project,
        stage=stage,
        tier=DeliverableTier.CORE_REQUIRED,
    ).exclude(status__in=[DeliverableStatus.EXEMPTED, DeliverableStatus.VOIDED])
    for deliverable in core_deliverables:
        ok = deliverable.status in {
            DeliverableStatus.CONFIRMED,
            DeliverableStatus.CONTROLLED,
            DeliverableStatus.EXEMPTED,
        }
        if deliverable.requires_professional_confirmation and deliverable.current_revision_id:
            confirmed = ProfessionalConfirmation.objects.filter(
                deliverable_revision_id=deliverable.current_revision_id,
                status=ProfessionalConfirmationStatus.APPROVED,
            ).exists()
            ok = confirmed or deliverable.status == DeliverableStatus.EXEMPTED
        if not ok and deliverable.status != DeliverableStatus.EXEMPTED:
            blocks.append(
                {
                    "code": "CORE_DELIVERABLE_NOT_READY",
                    "message": f"Core deliverable {deliverable.deliverable_code} is not ready.",
                }
            )

    pending_confirmations = ProfessionalConfirmation.objects.filter(
        deliverable_revision__deliverable__project=project,
        deliverable_revision__deliverable__stage=stage,
        status=ProfessionalConfirmationStatus.PENDING,
    )
    if pending_confirmations.exists():
        blocks.append(
            {
                "code": "PROFESSIONAL_CONFIRMATION_PENDING",
                "message": "Professional confirmations are still pending.",
            }
        )

    if project.product_draft_id is None:
        blocks.append(
            {
                "code": "PRODUCT_DRAFT_MISSING",
                "message": "Product draft is required for gate submission.",
            }
        )

    if ExecutionException.objects.filter(
        project=project,
        stage=stage,
        status=ExecutionExceptionStatus.PENDING,
    ).exists():
        blocks.append(
            {
                "code": "STAGE_EXCEPTION_PENDING",
                "message": "Stage handling exceptions await confirmation.",
            }
        )

    inactive_revisions = DeliverableRevision.objects.filter(
        deliverable__project=project,
        deliverable__stage=stage,
        document_version__file_object__storage_status=StorageStatus.ACTIVE,
    )
    del inactive_revisions  # presence of ACTIVE is fine; check non-active current files:
    for revision in DeliverableRevision.objects.filter(
        deliverable__project=project,
        deliverable__stage=stage,
        pk__in=Deliverable.objects.filter(
            project=project, stage=stage, current_revision__isnull=False
        ).values_list("current_revision_id", flat=True),
    ).select_related("document_version__file_object"):
        if revision.document_version.file_object.storage_status != StorageStatus.ACTIVE:
            blocks.append(
                {
                    "code": "FILE_NOT_ACTIVE",
                    "message": "Referenced file object is not ACTIVE.",
                }
            )
            break

    if EmergencyExecution.objects.filter(
        project=project,
        status__in=[EmergencyExecutionStatus.OPEN, EmergencyExecutionStatus.OVERDUE],
    ).exists():
        blocks.append(
            {
                "code": "EMERGENCY_EXECUTION_OPEN",
                "message": "Blocking emergency execution items remain open.",
            }
        )

    if stage.planned_end_at is None:
        warnings.append(
            {
                "code": "PLAN_INCOMPLETE",
                "message": "Stage planned end date is missing.",
            }
        )

    return GateValidationResult(blocks=blocks, warnings=warnings)
