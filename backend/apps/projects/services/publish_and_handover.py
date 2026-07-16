"""Publish approved product draft and initialize monitoring after FIRST_LAUNCH."""

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
from apps.operations.models import MonitoringScope
from apps.operations.services.initialize_monitoring_scope import InitializeMonitoringScope
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.errors import ProductPublicationFailed
from apps.products.models import ChangeSetType, ProductVersion
from apps.products.services.publish_change_set import PublishProductChangeSet
from apps.projects.models import Project, ProjectStageStatus, ProjectStatus
from apps.stage_gates.models import GateDecision, GateResult, MajorGateDecision


@dataclass(frozen=True)
class HandoverResult:
    project: Project
    product_version: ProductVersion | None
    monitoring_scope: MonitoringScope | None
    error_code: str | None = None


@dataclass
class PublishAndHandover:
    context: CommandContext
    project_public_id: UUID
    decision_public_id: UUID
    idempotency_key: str

    def execute(self) -> HandoverResult:
        actor = self.context.actor
        with transaction.atomic():
            project = (
                Project.objects.select_for_update()
                .select_related("product_draft", "product_asset", "leader")
                .filter(
                    public_id=self.project_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if project is None:
                raise PermissionDeniedError()

            decision = (
                MajorGateDecision.objects.select_related("stage_gate")
                .filter(
                    public_id=self.decision_public_id,
                    organization_id=actor.organization_id,
                    stage_gate__project_id=project.id,
                )
                .first()
            )
            normal_decision: GateDecision | None = None
            if decision is None:
                normal_decision = (
                    GateDecision.objects.select_related("stage_gate")
                    .filter(
                        public_id=self.decision_public_id,
                        organization_id=actor.organization_id,
                        stage_gate__project_id=project.id,
                    )
                    .first()
                )
                if normal_decision is None:
                    raise PermissionDeniedError()
                approving_result = normal_decision.result
            else:
                approving_result = decision.final_decision
            if approving_result not in {
                GateResult.APPROVED,
                GateResult.APPROVED_WITH_EXCEPTION,
            }:
                raise ValidationFailedError(
                    details={"reason": "Decision is not an approving gate result."}
                )

            if decision is not None:
                decision_public_id = decision.public_id
            else:
                assert normal_decision is not None
                decision_public_id = normal_decision.public_id

            draft = project.product_draft
            if draft is None:
                raise ValidationFailedError(details={"reason": "Product draft is missing."})

            expected_key = f"{decision_public_id}:{draft.public_id}"
            if self.idempotency_key != expected_key:
                raise ValidationFailedError(
                    details={
                        "reason": (
                            "Idempotency key must be decision_public_id:change_set_public_id."
                        ),
                        "expected": expected_key,
                    }
                )

            existing_version = ProductVersion.objects.filter(change_set=draft).first()
            if project.status == ProjectStatus.OPERATING and existing_version is not None:
                scope = MonitoringScope.objects.filter(
                    project=project,
                    source_decision_public_id=decision_public_id,
                ).first()
                return HandoverResult(
                    project=project,
                    product_version=existing_version,
                    monitoring_scope=scope,
                )

            publish_action = (
                "product.publish_new"
                if draft.change_type == ChangeSetType.NEW_PRODUCT
                else "product.publish_iteration"
            )
            auth = authorize(
                subject_for(actor),
                action=publish_action,
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=draft.product.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth.allowed:
                raise PermissionDeniedError()

            try:
                with transaction.atomic():
                    publication = PublishProductChangeSet(
                        context=self.context,
                        change_set_public_id=draft.public_id,
                        idempotency_key=self.idempotency_key,
                    ).execute()
                    scope = InitializeMonitoringScope(
                        project=project,
                        product_version=publication.product_version,
                        owner=project.leader,
                        source_decision_public_id=decision_public_id,
                        effective_at=self.context.occurred_at,
                    ).execute()
                    project.status = ProjectStatus.OPERATING
                    project.save(update_fields=["status", "updated_at"])
                    self._advance_post_launch_stages(project)
                    append_event(
                        AuditRecord(
                            actor=actor,
                            action_code=publish_action,
                            resource_type="project",
                            resource_public_id=project.public_id,
                            result=AuditResult.SUCCESS,
                            trace_id=self.context.trace_id,
                            occurred_at=self.context.occurred_at,
                            acting_roles_snapshot=acting_roles_snapshot(actor),
                            after_summary={
                                "decision_public_id": str(decision_public_id),
                                "product_version_public_id": str(
                                    publication.product_version.public_id
                                ),
                                "monitoring_scope_public_id": str(scope.public_id),
                            },
                        )
                    )
                    register_outbox_event(
                        OutboxMessage(
                            event_type="project.handed_over",
                            aggregate_type="project",
                            aggregate_id=project.public_id,
                            payload={
                                "project_public_id": str(project.public_id),
                                "decision_public_id": str(decision_public_id),
                                "product_version_public_id": str(
                                    publication.product_version.public_id
                                ),
                            },
                            occurred_at=self.context.occurred_at,
                        )
                    )
                    return HandoverResult(
                        project=project,
                        product_version=publication.product_version,
                        monitoring_scope=scope,
                    )
            except (ProductPublicationFailed, ValidationFailedError) as exc:
                project.status = ProjectStatus.PUBLISH_PENDING_REPAIR
                project.save(update_fields=["status", "updated_at"])
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code=publish_action,
                        resource_type="project",
                        resource_public_id=project.public_id,
                        result=AuditResult.FAILURE,
                        trace_id=self.context.trace_id,
                        occurred_at=self.context.occurred_at,
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        after_summary={"error": getattr(exc, "code", type(exc).__name__)},
                    )
                )
                return HandoverResult(
                    project=project,
                    product_version=None,
                    monitoring_scope=None,
                    error_code="PRODUCT_PUBLICATION_FAILED",
                )

    def _advance_post_launch_stages(self, project: Project) -> None:
        l2 = project.stages.filter(stage_code="L2").first()
        if l2 is not None:
            l2.status = ProjectStageStatus.COMPLETED
            l2.save(update_fields=["status", "updated_at"])
        l3 = project.stages.filter(stage_code="L3").first()
        if l3 is not None:
            l3.status = ProjectStageStatus.ACTIVE
            l3.actual_start_at = self.context.occurred_at
            l3.save(update_fields=["status", "actual_start_at", "updated_at"])
            project.current_stage = l3
            project.save(update_fields=["current_stage", "updated_at"])


@dataclass
class RetryPublishAndHandover:
    """Re-run PublishAndHandover for PUBLISH_PENDING_REPAIR using the original decision."""

    context: CommandContext
    project_public_id: UUID

    def execute(self) -> HandoverResult:
        actor = self.context.actor
        with transaction.atomic():
            project = (
                Project.objects.select_for_update()
                .select_related("product_draft")
                .filter(
                    public_id=self.project_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if project is None:
                raise PermissionDeniedError()

            auth = authorize(
                subject_for(actor),
                action="project.publish_repair",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=project.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth.allowed:
                raise PermissionDeniedError()

            if project.status not in {
                ProjectStatus.PUBLISH_PENDING_REPAIR,
                ProjectStatus.OPERATING,
            }:
                raise ValidationFailedError(
                    details={"reason": "Project is not awaiting publish repair."}
                )

            decision = (
                MajorGateDecision.objects.filter(
                    organization_id=project.organization_id,
                    stage_gate__project_id=project.id,
                    stage_gate__stage_code="FIRST_LAUNCH",
                )
                .exclude(final_decision="")
                .order_by("-decided_at")
                .first()
            )
            if decision is None:
                raise ValidationFailedError(
                    details={"reason": "No FIRST_LAUNCH final decision found for repair."}
                )
            draft = project.product_draft
            if draft is None:
                raise ValidationFailedError(details={"reason": "Product draft is missing."})

        return PublishAndHandover(
            context=self.context,
            project_public_id=project.public_id,
            decision_public_id=decision.public_id,
            idempotency_key=f"{decision.public_id}:{draft.public_id}",
        ).execute()
