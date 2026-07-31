"""Submit PRODUCT_RETIREMENT gate with immutable material references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.operations.models import RetirementPlan
from apps.operations.services.retirement_plans import (
    ApplyRetirementSubmission,
    validate_retirement_plan_completeness,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import (
    GateStatus,
    GateSubmission,
    GateSubmissionMaterialReference,
    MaterialType,
    StageGateInstance,
    SubjectType,
)


@dataclass
class SubmitRetirementGate:
    context: CommandContext
    plan_public_id: UUID
    idempotency_key: str

    def execute(self) -> GateSubmission:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        key = (self.idempotency_key or "").strip()
        if not key:
            raise ValidationFailedError(message="idempotency_key is required.")

        with transaction.atomic():
            plan = (
                RetirementPlan.objects.select_for_update()
                .select_related("operating_snapshot", "product")
                .filter(organization_id=actor.organization_id, public_id=self.plan_public_id)
                .first()
            )
            if plan is None or plan.stage_gate_public_id is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="retirement_plan.submit",
                resource=ResourceDescriptor(
                    resource_type="retirement_plan",
                    public_id=plan.public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            gate = (
                StageGateInstance.objects.select_for_update()
                .filter(
                    organization_id=actor.organization_id,
                    public_id=plan.stage_gate_public_id,
                    subject_type=SubjectType.RETIREMENT_PLAN,
                    subject_public_id=plan.public_id,
                    stage_code="PRODUCT_RETIREMENT",
                )
                .first()
            )
            if gate is None:
                raise PermissionDeniedError()

            existing = GateSubmission.objects.filter(stage_gate=gate, idempotency_key=key).first()
            if existing is not None:
                return existing

            validate_retirement_plan_completeness(plan)
            plan = ApplyRetirementSubmission(
                context=self.context,
                plan_public_id=plan.public_id,
                organization_id=actor.organization_id,
            ).execute()

            assert plan.stop_production_at is not None
            assert plan.stop_sale_at is not None
            assert plan.retire_at is not None
            snapshot_json = {
                "plan_public_id": str(plan.public_id),
                "plan_content_hash": plan.content_hash,
                "scope_snapshot": plan.scope_snapshot,
                "dates": {
                    "stop_production_at": plan.stop_production_at.isoformat(),
                    "stop_sale_at": plan.stop_sale_at.isoformat(),
                    "retire_at": plan.retire_at.isoformat(),
                },
            }
            content_hash = hashlib.sha256(
                json.dumps(snapshot_json, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()

            next_number = (
                GateSubmission.objects.filter(stage_gate=gate).aggregate(Max("submission_number"))[
                    "submission_number__max"
                ]
                or 0
            ) + 1
            try:
                submission = GateSubmission.objects.create(
                    organization_id=actor.organization_id,
                    stage_gate=gate,
                    submission_number=next_number,
                    snapshot_json=snapshot_json,
                    content_hash=content_hash,
                    validation_result_json={"ok": True},
                    submitted_by=actor,
                    submitted_at=now,
                    idempotency_key=key,
                )
            except IntegrityError:
                return GateSubmission.objects.get(stage_gate=gate, idempotency_key=key)

            materials = [
                (
                    MaterialType.RETIREMENT_PLAN,
                    plan.public_id,
                    plan.content_hash,
                ),
            ]
            if plan.operating_snapshot is not None:
                materials.append(
                    (
                        MaterialType.OPERATING_DATA_SNAPSHOT,
                        plan.operating_snapshot.public_id,
                        plan.operating_snapshot.content_hash,
                    )
                )
            if plan.document_version_public_id:
                materials.append(
                    (
                        MaterialType.DOCUMENT_VERSION,
                        plan.document_version_public_id,
                        plan.document_version_hash,
                    )
                )
            for material_type, material_id, material_hash in materials:
                GateSubmissionMaterialReference.objects.create(
                    organization_id=actor.organization_id,
                    submission=submission,
                    material_type=material_type,
                    material_public_id=material_id,
                    content_hash=material_hash or "",
                    locked_at=now,
                )

            gate.status = GateStatus.SUBMITTED
            gate.current_submission = submission
            gate.open_material_key = None
            gate.save(
                update_fields=[
                    "status",
                    "current_submission",
                    "open_material_key",
                    "updated_at",
                ]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="retirement_plan.submit",
                    resource_type="retirement_plan",
                    resource_public_id=plan.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "submission_public_id": str(submission.public_id),
                        "content_hash": content_hash,
                    },
                )
            )
            return submission
