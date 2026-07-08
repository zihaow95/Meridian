"""Update a single case assessment conclusion, status and controlled deliverable."""

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
from apps.documents.models import DocumentVersion, VersionStatus
from apps.opportunities.errors import (
    CaseAssessmentNotEditable,
    ControlledDeliverableRequired,
)
from apps.opportunities.models import (
    AssessmentStatus,
    CandidateStatus,
    CaseAssessment,
    ProjectCandidate,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext

_EDITABLE_CANDIDATE_STATES = {CandidateStatus.ASSESSING, CandidateStatus.NEEDS_INFO}


@dataclass
class UpdateCaseAssessment:
    context: CommandContext
    candidate_public_id: UUID
    category_code: str
    conclusion: str | None = None
    status: str | None = None
    deliverable_version_public_id: UUID | None = None

    def execute(self) -> CaseAssessment:
        actor = self.context.actor
        now = self.context.occurred_at

        if self.status is not None and self.status not in AssessmentStatus.values:
            raise ValidationFailedError(message="Unknown assessment status.")

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
                action="candidate.assessment.edit",
                resource=ResourceDescriptor(
                    resource_type="project_candidate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if candidate.status not in _EDITABLE_CANDIDATE_STATES:
                raise CaseAssessmentNotEditable()

            assessment = CaseAssessment.objects.filter(
                candidate=candidate,
                category_code=self.category_code,
            ).first()
            if assessment is None:
                raise PermissionDeniedError()

            if self.deliverable_version_public_id is not None:
                self._assert_controlled_deliverable(
                    candidate, self.deliverable_version_public_id
                )
                assessment.deliverable_version_public_id = self.deliverable_version_public_id
            if self.conclusion is not None:
                assessment.conclusion = self.conclusion
            if self.status is not None:
                assessment.status = self.status
            assessment.save()

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="candidate.assessment.edit",
                    resource_type="project_candidate",
                    resource_public_id=candidate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "category_code": assessment.category_code,
                        "status": assessment.status,
                    },
                )
            )

        return assessment

    def _assert_controlled_deliverable(
        self, candidate: ProjectCandidate, version_public_id: UUID
    ) -> None:
        controlled = DocumentVersion.objects.filter(
            public_id=version_public_id,
            organization_id=candidate.organization_id,
            status=VersionStatus.CONTROLLED,
        ).exists()
        if not controlled:
            raise ControlledDeliverableRequired()
