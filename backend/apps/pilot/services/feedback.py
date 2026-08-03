"""Governed pilot feedback lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import F

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.models import DocumentVersion, StorageStatus, VersionStatus
from apps.identity.models.user import User, UserStatus
from apps.pilot.errors import FeedbackVersionConflict, PilotValidationError
from apps.pilot.models import (
    PilotBatch,
    PilotBatchStatus,
    PilotFeedback,
    PilotFeedbackSeverity,
    PilotFeedbackStatus,
)
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext

_OPEN_STATUSES = {
    PilotFeedbackStatus.OPEN,
    PilotFeedbackStatus.TRIAGED,
    PilotFeedbackStatus.IN_PROGRESS,
    PilotFeedbackStatus.READY_FOR_RETEST,
}


def _require_action(
    *,
    actor: User,
    action: str,
    resource_type: str,
    public_id: UUID | None,
    sensitivity_level: str = "INTERNAL",
) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type=resource_type,
            public_id=public_id,
            organization_id=actor.organization_id,
            sensitivity_level=sensitivity_level,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _lock_feedback(
    *,
    public_id: UUID,
    organization_id: int,
    expected_version: int | None,
) -> PilotFeedback:
    feedback = (
        PilotFeedback.objects.select_for_update()
        .select_related("batch")
        .filter(public_id=public_id, organization_id=organization_id)
        .first()
    )
    if feedback is None:
        raise PilotValidationError(message="feedback was not found.")
    if expected_version is not None and feedback.version_no != expected_version:
        raise FeedbackVersionConflict()
    return feedback


def _authorize_evidence(*, actor: User, version_public_id: UUID) -> DocumentVersion:
    version = (
        DocumentVersion.objects.select_related("file_object")
        .filter(
            public_id=version_public_id,
            organization_id=actor.organization_id,
        )
        .first()
    )
    if version is None:
        raise PilotValidationError(message="evidence document version was not found.")
    if version.status != VersionStatus.CONTROLLED:
        raise PilotValidationError(message="evidence must be a CONTROLLED document version.")
    if version.file_object.storage_status != StorageStatus.ACTIVE:
        raise PilotValidationError(message="evidence storage is not ACTIVE.")
    decision = authorize(
        subject_for(actor),
        action="document.version.download",
        resource=ResourceDescriptor(
            resource_type="document.version",
            public_id=version.public_id,
            organization_id=actor.organization_id,
            sensitivity_level=version.sensitivity_level,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()
    return version


def _bump(feedback: PilotFeedback, **fields: object) -> PilotFeedback:
    update_fields = list(fields.keys()) + ["version_no", "updated_at"]
    for key, value in fields.items():
        setattr(feedback, key, value)
    feedback.version_no = F("version_no") + 1
    feedback.save(update_fields=update_fields)
    feedback.refresh_from_db()
    return feedback


def _audit(
    *,
    context: CommandContext,
    feedback: PilotFeedback,
    action_code: str,
    reason: str,
    after: dict | None = None,
) -> None:
    append_event(
        AuditRecord(
            actor=context.actor,
            action_code=action_code,
            resource_type="pilot.feedback",
            resource_public_id=feedback.public_id,
            result=AuditResult.SUCCESS,
            trace_id=context.trace_id,
            occurred_at=context.occurred_at,
            after_summary={
                "status": feedback.status,
                "severity": feedback.severity,
                **(after or {}),
            },
            reason=reason,
        )
    )


@dataclass(frozen=True)
class OpenPilotFeedback:
    context: CommandContext
    batch_public_id: UUID
    title: str
    reproduction_summary: str
    external_key: str = ""
    evidence_document_version_public_id: UUID | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        title = self.title.strip()
        summary = self.reproduction_summary.strip()
        if not title:
            raise PilotValidationError(message="title is required.")
        if not summary:
            raise PilotValidationError(message="reproduction_summary is required.")

        with transaction.atomic():
            _require_action(
                actor=actor,
                action="pilot.feedback.create",
                resource_type="pilot.feedback",
                public_id=None,
            )
            batch = (
                PilotBatch.objects.select_for_update()
                .filter(
                    public_id=self.batch_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if batch is None:
                raise PilotValidationError(message="batch was not found.")
            if batch.status != PilotBatchStatus.OPEN:
                raise PilotValidationError(message="Feedback requires an OPEN batch.")

            key = self.external_key.strip()
            if key:
                existing = PilotFeedback.objects.filter(batch=batch, external_key=key).first()
                if existing is not None:
                    return existing

            evidence_id = None
            if self.evidence_document_version_public_id is not None:
                version = _authorize_evidence(
                    actor=actor,
                    version_public_id=self.evidence_document_version_public_id,
                )
                evidence_id = version.public_id

            feedback = PilotFeedback.objects.create(
                organization_id=actor.organization_id,
                batch=batch,
                reporter=actor,
                title=title,
                reproduction_summary=summary,
                external_key=key,
                evidence_document_version_public_id=evidence_id,
            )
            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.create",
                reason="OPENED",
            )
            return feedback


@dataclass(frozen=True)
class AssignPilotFeedback:
    context: CommandContext
    feedback_public_id: UUID
    severity: str
    assignee_public_id: UUID
    expected_version: int | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        if self.severity not in PilotFeedbackSeverity.values:
            raise PilotValidationError(message="severity is invalid.")

        with transaction.atomic():
            feedback = _lock_feedback(
                public_id=self.feedback_public_id,
                organization_id=actor.organization_id,
                expected_version=self.expected_version,
            )
            _require_action(
                actor=actor,
                action="pilot.feedback.assign",
                resource_type="pilot.feedback",
                public_id=feedback.public_id,
            )
            if feedback.status not in {
                PilotFeedbackStatus.OPEN,
                PilotFeedbackStatus.TRIAGED,
            }:
                raise PilotValidationError(message="Only OPEN or TRIAGED feedback can be assigned.")

            assignee = User.objects.filter(
                public_id=self.assignee_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if assignee is None:
                raise PilotValidationError(message="assignee was not found.")

            feedback = _bump(
                feedback,
                severity=self.severity,
                assignee=assignee,
                status=PilotFeedbackStatus.TRIAGED,
            )
            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.assign",
                reason="ASSIGNED",
                after={"assignee_public_id": str(assignee.public_id)},
            )
            return feedback


@dataclass(frozen=True)
class StartFeedbackHandling:
    context: CommandContext
    feedback_public_id: UUID
    expected_version: int | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        with transaction.atomic():
            feedback = _lock_feedback(
                public_id=self.feedback_public_id,
                organization_id=actor.organization_id,
                expected_version=self.expected_version,
            )
            _require_action(
                actor=actor,
                action="pilot.feedback.handle",
                resource_type="pilot.feedback",
                public_id=feedback.public_id,
            )
            if feedback.status == PilotFeedbackStatus.IN_PROGRESS:
                return feedback
            if feedback.status != PilotFeedbackStatus.TRIAGED:
                raise PilotValidationError(message="Only TRIAGED feedback can move to IN_PROGRESS.")
            feedback = _bump(feedback, status=PilotFeedbackStatus.IN_PROGRESS)
            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.handle",
                reason="IN_PROGRESS",
            )
            return feedback


@dataclass(frozen=True)
class SubmitFeedbackRetest:
    context: CommandContext
    feedback_public_id: UUID
    target_version: str = ""
    expected_version: int | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        with transaction.atomic():
            feedback = _lock_feedback(
                public_id=self.feedback_public_id,
                organization_id=actor.organization_id,
                expected_version=self.expected_version,
            )
            _require_action(
                actor=actor,
                action="pilot.feedback.handle",
                resource_type="pilot.feedback",
                public_id=feedback.public_id,
            )
            if feedback.status == PilotFeedbackStatus.READY_FOR_RETEST:
                return feedback
            if feedback.status != PilotFeedbackStatus.IN_PROGRESS:
                raise PilotValidationError(
                    message="Only IN_PROGRESS feedback can be submitted for retest."
                )
            feedback = _bump(
                feedback,
                status=PilotFeedbackStatus.READY_FOR_RETEST,
                target_version=self.target_version.strip(),
            )
            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.handle",
                reason="READY_FOR_RETEST",
            )
            return feedback


@dataclass(frozen=True)
class RetestPilotFeedback:
    context: CommandContext
    feedback_public_id: UUID
    passed: bool
    expected_version: int | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        with transaction.atomic():
            feedback = _lock_feedback(
                public_id=self.feedback_public_id,
                organization_id=actor.organization_id,
                expected_version=self.expected_version,
            )
            _require_action(
                actor=actor,
                action="pilot.feedback.retest",
                resource_type="pilot.feedback",
                public_id=feedback.public_id,
            )
            if feedback.status != PilotFeedbackStatus.READY_FOR_RETEST:
                raise PilotValidationError(
                    message="Only READY_FOR_RETEST feedback can be retested."
                )
            if self.passed:
                feedback = _bump(
                    feedback,
                    retest_result="PASSED",
                )
            else:
                feedback = _bump(
                    feedback,
                    status=PilotFeedbackStatus.IN_PROGRESS,
                    retest_result="FAILED",
                )
            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.retest",
                reason="PASSED" if self.passed else "FAILED",
            )
            return feedback


@dataclass(frozen=True)
class ClosePilotFeedback:
    context: CommandContext
    feedback_public_id: UUID
    reject: bool = False
    close_reason: str = ""
    workaround: str = ""
    target_version: str = ""
    accepted_by_public_id: UUID | None = None
    acceptance_note: str = ""
    expected_version: int | None = None

    def execute(self) -> PilotFeedback:
        actor = self.context.actor
        with transaction.atomic():
            feedback = _lock_feedback(
                public_id=self.feedback_public_id,
                organization_id=actor.organization_id,
                expected_version=self.expected_version,
            )
            _require_action(
                actor=actor,
                action="pilot.feedback.close",
                resource_type="pilot.feedback",
                public_id=feedback.public_id,
            )
            if feedback.status in {
                PilotFeedbackStatus.CLOSED,
                PilotFeedbackStatus.REJECTED,
            }:
                return feedback
            if feedback.status not in _OPEN_STATUSES:
                raise PilotValidationError(message="Feedback is not closable.")

            if self.reject:
                feedback = _bump(
                    feedback,
                    status=PilotFeedbackStatus.REJECTED,
                    close_reason=self.close_reason.strip() or "REJECTED",
                )
                _audit(
                    context=self.context,
                    feedback=feedback,
                    action_code="pilot.feedback.close",
                    reason="REJECTED",
                )
                return feedback

            severity = feedback.severity
            if not severity:
                raise PilotValidationError(message="severity is required before close.")

            if severity in {PilotFeedbackSeverity.P0, PilotFeedbackSeverity.P1}:
                if (
                    feedback.status != PilotFeedbackStatus.READY_FOR_RETEST
                    or feedback.retest_result != "PASSED"
                ):
                    raise PilotValidationError(
                        message="P0/P1 may close only after a passed retest."
                    )
                feedback = _bump(
                    feedback,
                    status=PilotFeedbackStatus.CLOSED,
                    close_reason=self.close_reason.strip() or "RETEST_PASSED",
                )
            elif severity == PilotFeedbackSeverity.P2:
                if (
                    feedback.status == PilotFeedbackStatus.READY_FOR_RETEST
                    and feedback.retest_result == "PASSED"
                ):
                    feedback = _bump(
                        feedback,
                        status=PilotFeedbackStatus.CLOSED,
                        close_reason=self.close_reason.strip() or "RETEST_PASSED",
                    )
                else:
                    if not self.workaround.strip():
                        raise PilotValidationError(message="P2 leftover requires a workaround.")
                    if not self.target_version.strip():
                        raise PilotValidationError(message="P2 leftover requires a target_version.")
                    if self.accepted_by_public_id is None:
                        raise PilotValidationError(
                            message="P2 leftover requires an accepted_by user."
                        )
                    acceptor = User.objects.filter(
                        public_id=self.accepted_by_public_id,
                        organization_id=actor.organization_id,
                        status=UserStatus.ACTIVE,
                    ).first()
                    if acceptor is None:
                        raise PilotValidationError(message="accepted_by was not found.")
                    if not self.acceptance_note.strip():
                        raise PilotValidationError(
                            message="P2 leftover requires a written acceptance_note."
                        )
                    feedback = _bump(
                        feedback,
                        status=PilotFeedbackStatus.CLOSED,
                        close_reason=self.close_reason.strip() or "P2_ACCEPTED_LEFTOVER",
                        workaround=self.workaround.strip(),
                        target_version=self.target_version.strip(),
                        accepted_by=acceptor,
                        acceptance_note=self.acceptance_note.strip(),
                    )
            else:
                # P3 may close into a follow-up list without a retest gate.
                feedback = _bump(
                    feedback,
                    status=PilotFeedbackStatus.CLOSED,
                    close_reason=self.close_reason.strip() or "CLOSED",
                    target_version=self.target_version.strip() or feedback.target_version,
                )

            _audit(
                context=self.context,
                feedback=feedback,
                action_code="pilot.feedback.close",
                reason="CLOSED",
            )
            return feedback
