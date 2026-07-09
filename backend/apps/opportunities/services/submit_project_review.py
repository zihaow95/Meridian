"""Submit a project candidate for the CASE_TO_PROJECT major stage gate.

Validates that every core assessment is resolved and that leadership, resource
risk and schedule inputs exist before opening the review gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.opportunities.errors import (
    CandidateVersionConflict,
    CaseAssessmentIncomplete,
    ProjectReviewInputsMissing,
    ProjectReviewNotSubmittable,
)
from apps.opportunities.models import (
    CORE_ASSESSMENT_CATEGORIES,
    RESOLVED_ASSESSMENT_STATUSES,
    CandidateStatus,
    CaseAssessment,
    ProjectCandidate,
)
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.stage_gates.models import (
    GateMaterialReference,
    GateStatus,
    MaterialType,
    StageCode,
    StageGateInstance,
    SubjectType,
)

_SUBMITTABLE = {CandidateStatus.ASSESSING, CandidateStatus.NEEDS_INFO}
_ALREADY_SUBMITTED = {CandidateStatus.IN_PROJECT_REVIEW}
_BLOCKED = {CandidateStatus.SOURCE_RECONFIRM_REQUIRED}


@dataclass
class SubmitProjectReview:
    context: CommandContext
    candidate_public_id: UUID
    version_no: int
    idempotency_key: str
    proposed_schedule: dict[str, Any] | None = None
    resource_risk_summary: str | None = None

    def execute(self) -> ProjectCandidate:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            candidate = (
                ProjectCandidate.objects.select_for_update()
                .filter(
                    public_id=self.candidate_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if candidate is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="candidate.submit_review",
                resource=ResourceDescriptor(
                    resource_type="project_candidate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if candidate.status in _ALREADY_SUBMITTED:
                return candidate
            if candidate.status in _BLOCKED:
                raise ProjectReviewNotSubmittable()
            if candidate.status not in _SUBMITTABLE:
                raise ProjectReviewNotSubmittable()
            if candidate.version_no != self.version_no:
                raise CandidateVersionConflict()

            if self.proposed_schedule is not None:
                candidate.proposed_schedule = self.proposed_schedule
            if self.resource_risk_summary is not None:
                candidate.resource_risk_summary = self.resource_risk_summary

            self._validate_inputs(candidate)
            self._validate_assessments(candidate)

            stage_gate = self._open_case_gate(candidate, now)

            candidate.status = CandidateStatus.IN_PROJECT_REVIEW
            candidate.version_no += 1
            candidate.save(
                update_fields=[
                    "proposed_schedule",
                    "resource_risk_summary",
                    "status",
                    "version_no",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="candidate.submit_review",
                    resource_type="project_candidate",
                    resource_public_id=candidate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"status": candidate.status},
                    request_metadata={"idempotency_key": self.idempotency_key},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="candidate.project_review_submitted",
                    aggregate_type="stage_gate",
                    aggregate_id=stage_gate.public_id,
                    payload={
                        "candidate_public_id": str(candidate.public_id),
                        "stage_gate_public_id": str(stage_gate.public_id),
                    },
                    occurred_at=now,
                )
            )

        return candidate

    def _validate_inputs(self, candidate: ProjectCandidate) -> None:
        missing: list[str] = []
        if candidate.case_owner_id is None:
            missing.append("case_owner")
        if not candidate.resource_risk_summary.strip():
            missing.append("resource_risk_summary")
        if not candidate.proposed_schedule:
            missing.append("proposed_schedule")
        if missing:
            raise ProjectReviewInputsMissing(missing=missing)

    def _validate_assessments(self, candidate: ProjectCandidate) -> None:
        resolved = dict(
            CaseAssessment.objects.filter(candidate=candidate).values_list(
                "category_code", "status"
            )
        )
        missing = [
            category
            for category in CORE_ASSESSMENT_CATEGORIES
            if resolved.get(category) not in RESOLVED_ASSESSMENT_STATUSES
        ]
        if missing:
            raise CaseAssessmentIncomplete(missing_categories=missing)

    def _open_case_gate(self, candidate: ProjectCandidate, now: datetime) -> StageGateInstance:
        active_exists = StageGateInstance.objects.filter(
            primary_material_type=MaterialType.CASE_ASSESSMENT,
            primary_material_public_id=candidate.public_id,
            status=GateStatus.OPEN,
        ).exists()
        if active_exists:
            raise ProjectReviewNotSubmittable()

        cycle_number = (
            StageGateInstance.objects.filter(
                subject_type=SubjectType.PROJECT_CANDIDATE,
                subject_public_id=candidate.public_id,
                stage_code=StageCode.CASE_TO_PROJECT,
            ).count()
            + 1
        )
        stage_gate = StageGateInstance.objects.create(
            organization=candidate.organization,
            subject_type=SubjectType.PROJECT_CANDIDATE,
            subject_public_id=candidate.public_id,
            stage_code=StageCode.CASE_TO_PROJECT,
            cycle_number=cycle_number,
            status=GateStatus.OPEN,
            primary_material_type=MaterialType.CASE_ASSESSMENT,
            primary_material_public_id=candidate.public_id,
        )
        GateMaterialReference.objects.create(
            organization=candidate.organization,
            stage_gate=stage_gate,
            material_type=MaterialType.CASE_ASSESSMENT,
            material_public_id=candidate.public_id,
            locked_at=now,
        )
        return stage_gate
