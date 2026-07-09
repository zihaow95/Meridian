"""Atomic project and product draft creation after CASE_TO_PROJECT approval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.opportunities.models import (
    CandidateSource,
    CandidateStatus,
    CandidateType,
    ProjectCandidate,
)
from apps.opportunities.services.configuration import get_opportunity_rule_snapshot
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import ProductDraft
from apps.products.services.create_draft_from_candidate import create_product_draft
from apps.projects.errors import ProjectCandidateNotApprovable, ProjectCreationFailed
from apps.projects.member_keys import active_member_key
from apps.projects.models import (
    Project,
    ProjectMember,
    ProjectOpportunitySource,
    ProjectRole,
    ProjectStatus,
    ProjectType,
)
from apps.stage_gates.errors import (
    MajorGateAlreadyDecided,
    MajorGateMaterialChanged,
    MajorGateRoleNotConfigured,
)
from apps.stage_gates.material_keys import close_gate_material_lock
from apps.stage_gates.models import (
    GateResult,
    GateStatus,
    MajorGateDecision,
    MaterialType,
    StageCode,
    StageGateInstance,
    SubjectType,
)

_APPROVING = frozenset({GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION})
_PROJECT_TYPE_BY_CANDIDATE = {
    CandidateType.NEW_PRODUCT: ProjectType.NEW_PRODUCT,
    CandidateType.PRODUCT_CHANGE: ProjectType.PRODUCT_CHANGE,
}


@dataclass(frozen=True)
class ApproveAndCreateProjectResult:
    project: Project
    product_draft: ProductDraft
    gate_decision: MajorGateDecision


@dataclass
class ApproveAndCreateProject:
    context: CommandContext
    candidate_public_id: UUID
    idempotency_key: str
    management_conclusion: str = GateResult.APPROVED
    final_decision: str = GateResult.APPROVED
    decision_summary: str = "Approved for project creation."

    def execute(self) -> ApproveAndCreateProjectResult:
        actor = self.context.actor
        now = self.context.occurred_at

        if self.management_conclusion not in GateResult.values:
            raise ProjectCandidateNotApprovable()
        if self.final_decision not in GateResult.values:
            raise ProjectCandidateNotApprovable()
        if GateResult(self.final_decision) not in _APPROVING:
            raise ProjectCandidateNotApprovable()

        with transaction.atomic():
            candidate = (
                ProjectCandidate.objects.select_for_update()
                .select_related("case_owner", "deputy_leader")
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
                action="major_gate.final_decision.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            management_decision = authorize(
                subject_for(actor),
                action="major_gate.management_conclusion.record",
                resource=ResourceDescriptor(
                    resource_type="stage_gate",
                    public_id=candidate.public_id,
                    organization_id=candidate.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not management_decision.allowed:
                raise PermissionDeniedError()

            existing_project = Project.objects.filter(candidate=candidate).first()
            if existing_project is not None:
                draft = ProductDraft.objects.filter(project_candidate=candidate).first()
                gate = self._latest_case_gate(candidate)
                gate_decision = (
                    MajorGateDecision.objects.filter(stage_gate=gate).first()
                    if gate is not None
                    else None
                )
                if (
                    gate_decision is not None
                    and gate_decision.idempotency_key == self.idempotency_key
                ):
                    if draft is None:
                        raise ProjectCreationFailed(message="Project exists without product draft.")
                    return ApproveAndCreateProjectResult(
                        project=existing_project,
                        product_draft=draft,
                        gate_decision=gate_decision,
                    )
                if candidate.status == CandidateStatus.PROJECT_CREATED and draft is not None:
                    if gate_decision is None:
                        raise ProjectCreationFailed(message="Project exists without gate decision.")
                    return ApproveAndCreateProjectResult(
                        project=existing_project,
                        product_draft=draft,
                        gate_decision=gate_decision,
                    )

            if candidate.status != CandidateStatus.IN_PROJECT_REVIEW:
                raise ProjectCandidateNotApprovable()
            if candidate.case_owner_id is None:
                raise ProjectCandidateNotApprovable()
            case_owner = candidate.case_owner
            if case_owner is None:
                raise ProjectCandidateNotApprovable()

            stage_gate = self._open_case_gate(candidate)
            if stage_gate is None:
                raise ProjectCandidateNotApprovable()

            existing_decision = MajorGateDecision.objects.filter(stage_gate=stage_gate).first()
            if existing_decision is not None:
                if existing_decision.idempotency_key == self.idempotency_key:
                    project = Project.objects.get(candidate=candidate)
                    draft = ProductDraft.objects.get(project_candidate=candidate)
                    return ApproveAndCreateProjectResult(
                        project=project,
                        product_draft=draft,
                        gate_decision=existing_decision,
                    )
                raise MajorGateAlreadyDecided()

            snapshot = get_opportunity_rule_snapshot(actor.organization, now)
            if not snapshot.final_decision_roles or not snapshot.management_conclusion_roles:
                raise MajorGateRoleNotConfigured()

            self._assert_material_unchanged(stage_gate, candidate)

            gate_decision = MajorGateDecision.objects.create(
                organization=candidate.organization,
                stage_gate=stage_gate,
                management_conclusion=self.management_conclusion,
                management_conclusion_by=actor,
                final_decision=self.final_decision,
                final_decision_by=actor,
                has_conclusion_difference=(self.management_conclusion != self.final_decision),
                decision_summary=self.decision_summary,
                idempotency_key=self.idempotency_key,
                decided_at=now,
            )
            stage_gate.status = GateStatus.DECIDED
            close_gate_material_lock(stage_gate)
            stage_gate.save(update_fields=["status", "open_material_key", "updated_at"])

            project = self._create_project(candidate, case_owner)
            try:
                product_asset, product_draft = create_product_draft(
                    candidate=candidate,
                    project=project,
                    actor=actor,
                    now=now,
                )
            except Exception as exc:
                raise ProjectCreationFailed() from exc
            project.product_asset = product_asset
            project.product_draft = product_draft
            project.save(update_fields=["product_asset", "product_draft", "updated_at"])

            self._create_members(candidate, project, actor, now, case_owner=case_owner)
            self._create_opportunity_sources(candidate, project, now)

            candidate.status = CandidateStatus.PROJECT_CREATED
            candidate.project_id = project.id
            candidate.version_no += 1
            candidate.save(update_fields=["status", "project_id", "version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="major_gate.final_decision.record",
                    resource_type="stage_gate",
                    resource_public_id=stage_gate.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "project_public_id": str(project.public_id),
                        "product_draft_public_id": str(product_draft.public_id),
                    },
                    request_metadata={"idempotency_key": self.idempotency_key},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="project.created",
                    aggregate_type="project",
                    aggregate_id=project.public_id,
                    payload={
                        "project_public_id": str(project.public_id),
                        "candidate_public_id": str(candidate.public_id),
                    },
                    occurred_at=now,
                )
            )

        return ApproveAndCreateProjectResult(
            project=project,
            product_draft=product_draft,
            gate_decision=gate_decision,
        )

    def _open_case_gate(self, candidate: ProjectCandidate) -> StageGateInstance | None:
        return StageGateInstance.objects.filter(
            subject_type=SubjectType.PROJECT_CANDIDATE,
            subject_public_id=candidate.public_id,
            stage_code=StageCode.CASE_TO_PROJECT,
            status=GateStatus.OPEN,
        ).first()

    def _latest_case_gate(self, candidate: ProjectCandidate) -> StageGateInstance | None:
        return (
            StageGateInstance.objects.filter(
                subject_type=SubjectType.PROJECT_CANDIDATE,
                subject_public_id=candidate.public_id,
                stage_code=StageCode.CASE_TO_PROJECT,
            )
            .order_by("-created_at")
            .first()
        )

    def _assert_material_unchanged(
        self, stage_gate: StageGateInstance, candidate: ProjectCandidate
    ) -> None:
        if stage_gate.primary_material_type != MaterialType.CASE_ASSESSMENT:
            raise MajorGateMaterialChanged()
        if stage_gate.primary_material_public_id != candidate.public_id:
            raise MajorGateMaterialChanged()

    def _create_project(self, candidate: ProjectCandidate, case_owner: User) -> Project:
        try:
            return Project.objects.create(
                organization=candidate.organization,
                business_no=f"PRJ-{uuid.uuid4().hex[:8].upper()}",
                name=candidate.name,
                project_type=_PROJECT_TYPE_BY_CANDIDATE.get(
                    CandidateType(candidate.candidate_type), ProjectType.NEW_PRODUCT
                ),
                status=ProjectStatus.INITIALIZING,
                candidate=candidate,
                leader=case_owner,
                deputy_leader=candidate.deputy_leader,
                idempotency_key=self.idempotency_key,
            )
        except IntegrityError as exc:
            raise ProjectCreationFailed(message="Project already exists for candidate.") from exc

    def _create_members(
        self,
        candidate: ProjectCandidate,
        project: Project,
        actor: User,
        now: datetime,
        *,
        case_owner: User,
    ) -> None:
        ProjectMember.objects.create(
            organization=candidate.organization,
            project=project,
            user=case_owner,
            project_role=ProjectRole.LEADER,
            active_role_key=active_member_key(project.id, case_owner.id, ProjectRole.LEADER),
            active_from=now,
            appointed_by=actor,
        )
        deputy_leader = candidate.deputy_leader
        if deputy_leader is not None:
            ProjectMember.objects.create(
                organization=candidate.organization,
                project=project,
                user=deputy_leader,
                project_role=ProjectRole.DEPUTY,
                active_role_key=active_member_key(
                    project.id,
                    deputy_leader.id,
                    ProjectRole.DEPUTY,
                ),
                active_from=now,
                appointed_by=actor,
            )

    def _create_opportunity_sources(
        self,
        candidate: ProjectCandidate,
        project: Project,
        now: datetime,
    ) -> None:
        for source in CandidateSource.objects.filter(candidate=candidate, is_active=True):
            ProjectOpportunitySource.objects.create(
                organization=candidate.organization,
                project=project,
                opportunity=source.opportunity,
                source_role=source.source_role,
                linked_at=now,
            )
