"""Create immutable execution gate submissions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.errors import GateSubmissionBlocked
from apps.stage_gates.models import (
    GateStatus,
    GateSubmission,
    GateSubmissionMaterialReference,
    MaterialType,
    StageGateInstance,
)
from apps.stage_gates.services.validate_execution_gate import collect_execution_gate_validation
from apps.work_items.models import Deliverable, Task


@dataclass
class SubmitExecutionGate:
    context: CommandContext
    stage_gate_public_id: UUID
    idempotency_key: str

    def execute(self) -> GateSubmission:
        actor = self.context.actor
        with transaction.atomic():
            gate = (
                StageGateInstance.objects.select_for_update()
                .select_related("project", "project_stage")
                .filter(
                    public_id=self.stage_gate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if gate is None or gate.project_id is None:
                raise PermissionDeniedError()

            existing = GateSubmission.objects.filter(
                stage_gate=gate,
                idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None:
                return existing

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

            if gate.status not in {
                GateStatus.READY,
                GateStatus.NEEDS_INFO,
                GateStatus.OPEN,
            }:
                raise GateSubmissionBlocked(message="Gate is not open for submission.")

            validation = collect_execution_gate_validation(gate)
            if validation.blocks:
                raise GateSubmissionBlocked(
                    details={"blocks": validation.blocks, "warnings": validation.warnings}
                )

            snapshot = _build_submission_snapshot(gate)
            content_hash = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            next_number = (
                GateSubmission.objects.filter(stage_gate=gate).aggregate(
                    Max("submission_number")
                )["submission_number__max"]
                or 0
            ) + 1

            try:
                submission = GateSubmission.objects.create(
                    organization=gate.organization,
                    stage_gate=gate,
                    submission_number=next_number,
                    snapshot_json=snapshot,
                    content_hash=content_hash,
                    validation_result_json={
                        "blocks": validation.blocks,
                        "warnings": validation.warnings,
                    },
                    submitted_by=actor,
                    submitted_at=self.context.occurred_at,
                    idempotency_key=self.idempotency_key,
                )
            except IntegrityError:
                existing = GateSubmission.objects.get(
                    stage_gate=gate,
                    idempotency_key=self.idempotency_key,
                )
                return existing

            for item in snapshot.get("material_refs", []):
                GateSubmissionMaterialReference.objects.create(
                    organization=gate.organization,
                    submission=submission,
                    material_type=item["material_type"],
                    material_public_id=item["material_public_id"],
                    content_hash=item.get("content_hash", ""),
                    locked_at=self.context.occurred_at,
                )

            gate.status = GateStatus.SUBMITTED
            gate.current_submission = submission
            gate.save(update_fields=["status", "current_submission", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="stage_gate.submit",
                    resource_type="stage_gate",
                    resource_public_id=gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "submission_public_id": str(submission.public_id),
                        "submission_number": submission.submission_number,
                        "content_hash": content_hash,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="stage_gate.submitted",
                    aggregate_type="stage_gate",
                    aggregate_id=gate.public_id,
                    payload={
                        "stage_gate_public_id": str(gate.public_id),
                        "submission_public_id": str(submission.public_id),
                    },
                    occurred_at=self.context.occurred_at,
                )
            )
            return submission


def _build_submission_snapshot(gate: StageGateInstance) -> dict:
    project = gate.project
    stage = gate.project_stage
    assert project is not None and stage is not None
    tasks = [
        {
            "public_id": str(task.public_id),
            "task_code": task.task_code,
            "status": task.status,
            "is_core": task.is_core,
        }
        for task in Task.objects.filter(project=project, stage=stage).order_by("task_code")
    ]
    deliverables = []
    material_refs = []
    for deliverable in Deliverable.objects.filter(project=project, stage=stage).order_by(
        "deliverable_code"
    ):
        entry = {
            "public_id": str(deliverable.public_id),
            "deliverable_code": deliverable.deliverable_code,
            "status": deliverable.status,
            "tier": deliverable.tier,
            "current_revision_public_id": (
                str(deliverable.current_revision.public_id)
                if deliverable.current_revision_id
                else None
            ),
        }
        deliverables.append(entry)
        if deliverable.current_revision_id:
            revision = deliverable.current_revision
            material_refs.append(
                {
                    "material_type": MaterialType.DELIVERABLE_REVISION,
                    "material_public_id": str(revision.public_id),
                    "content_hash": revision.content_hash,
                }
            )
    return {
        "project_public_id": str(project.public_id),
        "stage_code": stage.stage_code,
        "tasks": tasks,
        "deliverables": deliverables,
        "product_draft_public_id": (
            str(project.product_draft.public_id) if project.product_draft_id else None
        ),
        "material_refs": material_refs,
    }
