"""Retirement plan creation, validation helpers, and dated execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.models import DocumentVersion, VersionStatus
from apps.identity.models.user import User
from apps.operations.errors import RetirementNotExecutable, RetirementSubmissionIncomplete
from apps.operations.models import (
    IssueSourceType,
    OperatingDataSnapshot,
    OperatingIssue,
    OperatingIssueStatus,
    RetirementActionStatus,
    RetirementActionType,
    RetirementExecutionAction,
    RetirementPlan,
    RetirementPlanStatus,
)
from apps.operations.services.operating_issues import CreateOperatingIssue
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import ProductAsset
from apps.products.services.retirement import ApplyApprovedRetirementAction
from apps.stage_gates.models import GateResult
from apps.stage_gates.services.create_retirement_gate import CreateRetirementGate


def _authorize(actor: User, *, action: str, plan: RetirementPlan | None = None) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="retirement_plan",
            public_id=plan.public_id if plan is not None else None,
            organization_id=actor.organization_id,
            metadata={
                "product_public_id": str(plan.product.public_id) if plan is not None else None
            },
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def validate_retirement_plan_completeness(plan: RetirementPlan) -> dict[str, Any]:
    missing: list[str] = []
    scope = plan.scope_snapshot or {}
    if not scope.get("product_version_public_ids"):
        missing.append("scope.product_version_public_ids")
    if not scope.get("sku_public_ids"):
        missing.append("scope.sku_public_ids")
    if not scope.get("channel_public_ids"):
        missing.append("scope.channel_public_ids")
    if plan.operating_snapshot is None:
        missing.append("operating_snapshot")
    else:
        payload = plan.operating_snapshot.payload_json or {}
        for key in ("sales", "gross_margin", "inventory", "near_expiry", "complaints"):
            if key not in payload:
                missing.append(f"snapshot.{key}")
    if not plan.inventory_plan:
        missing.append("inventory_plan")
    if not plan.supply_contract_impact:
        missing.append("supply_contract_impact")
    if not plan.customer_market_plan:
        missing.append("customer_market_plan")
    if not plan.replacement_plan:
        missing.append("replacement_plan")
    if plan.stop_production_at is None:
        missing.append("stop_production_at")
    if plan.stop_sale_at is None:
        missing.append("stop_sale_at")
    if plan.retire_at is None:
        missing.append("retire_at")
    if plan.document_version_public_id is None:
        missing.append("document_version")
    else:
        doc = (
            DocumentVersion.objects.select_related("file_object", "document")
            .filter(
                organization_id=plan.organization_id,
                public_id=plan.document_version_public_id,
            )
            .first()
        )
        if doc is None or doc.status != VersionStatus.CONTROLLED:
            missing.append("document_version.controlled")
    coverage = None
    if plan.operating_snapshot is not None:
        coverage = (plan.operating_snapshot.payload_json or {}).get("coverage_status")
    if coverage == "INSUFFICIENT" and not (plan.coverage_gap_explanation or "").strip():
        missing.append("coverage_gap_explanation")
    if missing:
        raise RetirementSubmissionIncomplete(details={"missing": missing})
    return {"ok": True, "missing": []}


@dataclass
class CreateRetirementPlan:
    context: CommandContext
    product_public_id: UUID
    scope_snapshot: dict[str, Any]
    inventory_plan: dict[str, Any] = field(default_factory=dict)
    supply_contract_impact: dict[str, Any] = field(default_factory=dict)
    customer_market_plan: dict[str, Any] = field(default_factory=dict)
    replacement_plan: dict[str, Any] = field(default_factory=dict)
    stop_production_at: date | None = None
    stop_sale_at: date | None = None
    retire_at: date | None = None
    issue_public_id: UUID | None = None
    source_type: str = IssueSourceType.DIRECT
    source_materials_json: dict[str, Any] | None = None
    coverage_gap_explanation: str = ""
    operating_snapshot_public_id: UUID | None = None
    document_version_public_id: UUID | None = None

    def execute(self) -> RetirementPlan:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            _authorize(actor, action="retirement_plan.create")
            product = ProductAsset.objects.filter(
                organization_id=actor.organization_id, public_id=self.product_public_id
            ).first()
            if product is None:
                raise PermissionDeniedError()

            if self.issue_public_id is not None:
                issue = OperatingIssue.objects.filter(
                    organization_id=actor.organization_id, public_id=self.issue_public_id
                ).first()
                if issue is None:
                    raise PermissionDeniedError()
            else:
                issue = CreateOperatingIssue(
                    context=self.context,
                    title=f"Retirement: {product.name}",
                    product_public_id=product.public_id,
                    phenomenon_summary="Direct retirement initiation",
                    source_type=self.source_type or IssueSourceType.DIRECT,
                    source_materials_json=self.source_materials_json
                    or {"reason": "direct_retirement"},
                ).execute()

            snapshot = None
            if self.operating_snapshot_public_id is not None:
                snapshot = OperatingDataSnapshot.objects.filter(
                    organization_id=actor.organization_id,
                    public_id=self.operating_snapshot_public_id,
                ).first()
                if snapshot is None:
                    raise ValidationFailedError(message="Operating snapshot not found.")

            doc_hash = ""
            if self.document_version_public_id is not None:
                doc = (
                    DocumentVersion.objects.select_related("file_object")
                    .filter(
                        organization_id=actor.organization_id,
                        public_id=self.document_version_public_id,
                    )
                    .first()
                )
                if doc is not None:
                    doc_hash = doc.file_object.sha256

            plan = RetirementPlan(
                organization_id=actor.organization_id,
                product=product,
                issue=issue,
                scope_snapshot=dict(self.scope_snapshot or {}),
                inventory_plan=dict(self.inventory_plan or {}),
                supply_contract_impact=dict(self.supply_contract_impact or {}),
                customer_market_plan=dict(self.customer_market_plan or {}),
                replacement_plan=dict(self.replacement_plan or {}),
                coverage_gap_explanation=self.coverage_gap_explanation or "",
                operating_snapshot=snapshot,
                document_version_public_id=self.document_version_public_id,
                document_version_hash=doc_hash,
                stop_production_at=self.stop_production_at,
                stop_sale_at=self.stop_sale_at,
                retire_at=self.retire_at,
                status=RetirementPlanStatus.DRAFT,
                created_by=actor,
            )
            plan.content_hash = plan.compute_content_hash()
            plan.save()

            gate = CreateRetirementGate(
                context=self.context,
                plan_public_id=plan.public_id,
                organization_id=actor.organization_id,
            ).execute()
            plan.stage_gate_public_id = gate.public_id
            plan.save(update_fields=["stage_gate_public_id", "updated_at"])

            if issue.status not in {
                OperatingIssueStatus.RETIREMENT_REVIEW,
                OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
                OperatingIssueStatus.CLOSED,
            }:
                issue.status = OperatingIssueStatus.RETIREMENT_REVIEW
                issue.version_no += 1
                issue.save(update_fields=["status", "version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="retirement_plan.create",
                    resource_type="retirement_plan",
                    resource_public_id=plan.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "issue_public_id": str(issue.public_id),
                        "stage_gate_public_id": str(gate.public_id),
                    },
                )
            )
            return plan


@dataclass
class ExecuteRetirementPlan:
    context: CommandContext
    plan_public_id: UUID
    as_of: date | None = None

    def execute(self) -> RetirementPlan:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        as_of = self.as_of or now.date()
        with transaction.atomic():
            plan = (
                RetirementPlan.objects.select_for_update()
                .select_related("product", "issue")
                .filter(organization_id=actor.organization_id, public_id=self.plan_public_id)
                .first()
            )
            if plan is None:
                raise PermissionDeniedError()
            _authorize(actor, action="retirement_plan.execute", plan=plan)
            if plan.status not in {
                RetirementPlanStatus.APPROVED,
                RetirementPlanStatus.EXECUTING,
                RetirementPlanStatus.EXECUTION_ERROR,
                RetirementPlanStatus.COMPLETED,
            }:
                raise RetirementNotExecutable()

            if plan.status == RetirementPlanStatus.COMPLETED:
                return plan

            plan.status = RetirementPlanStatus.EXECUTING
            plan.save(update_fields=["status", "updated_at"])

            actions = list(
                RetirementExecutionAction.objects.select_for_update()
                .filter(plan=plan)
                .order_by("scheduled_for", "id")
            )
            for action in actions:
                if action.status == RetirementActionStatus.COMPLETED:
                    continue
                if action.scheduled_for > as_of:
                    continue
                action.attempt_count += 1
                try:
                    with transaction.atomic():
                        ApplyApprovedRetirementAction(
                            context=self.context,
                            action_type=action.action_type,
                            product_public_id=plan.product.public_id,
                            scope_snapshot=plan.scope_snapshot,
                            as_of=as_of,
                        ).execute()
                        action.status = RetirementActionStatus.COMPLETED
                        action.completed_at = now
                        action.last_error_code = ""
                        action.save(
                            update_fields=[
                                "status",
                                "completed_at",
                                "last_error_code",
                                "attempt_count",
                                "updated_at",
                            ]
                        )
                except Exception:  # noqa: BLE001 - capture per-action failure
                    action.status = RetirementActionStatus.FAILED
                    action.last_error_code = "EXECUTION_ERROR"
                    action.save(
                        update_fields=[
                            "status",
                            "last_error_code",
                            "attempt_count",
                            "updated_at",
                        ]
                    )
                    plan.status = RetirementPlanStatus.EXECUTION_ERROR
                    plan.save(update_fields=["status", "updated_at"])
                    register_outbox_event(
                        OutboxMessage(
                            event_type="retirement.execution_failed",
                            aggregate_type="retirement_plan",
                            aggregate_id=plan.public_id,
                            payload={
                                "plan_public_id": str(plan.public_id),
                                "action_type": action.action_type,
                                "error_code": "EXECUTION_ERROR",
                            },
                            occurred_at=now,
                        )
                    )
                    return plan

            if actions and all(a.status == RetirementActionStatus.COMPLETED for a in actions):
                before_status = plan.status
                plan.status = RetirementPlanStatus.COMPLETED
                plan.save(update_fields=["status", "updated_at"])
                if plan.issue.status != OperatingIssueStatus.CLOSED:
                    plan.issue.status = OperatingIssueStatus.CLOSED
                    plan.issue.closed_at = now
                    plan.issue.closed_by = actor
                    plan.issue.version_no += 1
                    plan.issue.save(
                        update_fields=[
                            "status",
                            "closed_at",
                            "closed_by",
                            "version_no",
                            "updated_at",
                        ]
                    )
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code="retirement_plan.complete",
                        resource_type="retirement_plan",
                        resource_public_id=plan.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=self.context.trace_id,
                        occurred_at=now,
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        before_summary={"status": before_status},
                        after_summary={"status": plan.status},
                    )
                )
                register_outbox_event(
                    OutboxMessage(
                        event_type="retirement.completed",
                        aggregate_type="retirement_plan",
                        aggregate_id=plan.public_id,
                        payload={"plan_public_id": str(plan.public_id)},
                        occurred_at=now,
                    )
                )
            return plan


def seed_execution_actions(*, plan: RetirementPlan) -> None:
    mapping = [
        (RetirementActionType.STOP_PRODUCTION, plan.stop_production_at),
        (RetirementActionType.STOP_SALE, plan.stop_sale_at),
        (RetirementActionType.RETIRE, plan.retire_at),
    ]
    for action_type, scheduled in mapping:
        if scheduled is None:
            continue
        RetirementExecutionAction.objects.get_or_create(
            organization_id=plan.organization_id,
            plan=plan,
            action_type=action_type,
            defaults={
                "scheduled_for": scheduled,
                "status": RetirementActionStatus.PENDING,
            },
        )


_APPROVING_RESULTS = frozenset({GateResult.APPROVED, GateResult.APPROVED_WITH_EXCEPTION})


@dataclass
class ApplyRetirementSubmission:
    """Own the RetirementPlan writes for a gate submission.

    Called by ``SubmitRetirementGate`` so the stage_gates domain never writes
    RetirementPlan fields directly.
    """

    context: CommandContext
    plan_public_id: UUID
    organization_id: int

    def execute(self) -> RetirementPlan:
        plan = (
            RetirementPlan.objects.select_for_update()
            .select_related("operating_snapshot", "product")
            .filter(organization_id=self.organization_id, public_id=self.plan_public_id)
            .first()
        )
        if plan is None:
            raise PermissionDeniedError()
        plan.content_hash = plan.compute_content_hash()
        plan.status = RetirementPlanStatus.SUBMITTED
        plan.save(update_fields=["content_hash", "status", "updated_at"])
        return plan


@dataclass
class ApplyRetirementDecision:
    """Own the RetirementPlan writes for a PRODUCT_RETIREMENT final decision.

    Called by ``RecordRetirementFinalDecision`` so the stage_gates domain
    never writes RetirementPlan fields directly. Gate-level state (the
    MajorGateDecision record and StageGateInstance status) remains owned by
    stage_gates.
    """

    context: CommandContext
    plan_public_id: UUID
    organization_id: int
    stage_gate_public_id: UUID
    final_decision: str

    def execute(self) -> RetirementPlan:
        now = self.context.occurred_at or timezone.now()
        plan = (
            RetirementPlan.objects.select_for_update()
            .filter(organization_id=self.organization_id, public_id=self.plan_public_id)
            .first()
        )
        if plan is None:
            raise PermissionDeniedError()

        if self.final_decision in _APPROVING_RESULTS:
            plan.status = RetirementPlanStatus.APPROVED
            plan.approved_at = now
            plan.save(update_fields=["status", "approved_at", "updated_at"])
            seed_execution_actions(plan=plan)
            register_outbox_event(
                OutboxMessage(
                    event_type="retirement.approved",
                    aggregate_type="retirement_plan",
                    aggregate_id=plan.public_id,
                    payload={
                        "plan_public_id": str(plan.public_id),
                        "stage_gate_public_id": str(self.stage_gate_public_id),
                        "final_decision": self.final_decision,
                    },
                    occurred_at=now,
                )
            )
        elif self.final_decision == GateResult.PASSED:
            plan.status = RetirementPlanStatus.PASSED
            plan.save(update_fields=["status", "updated_at"])
        elif self.final_decision == GateResult.NEEDS_INFO:
            plan.status = RetirementPlanStatus.DRAFT
            plan.save(update_fields=["status", "updated_at"])
        elif self.final_decision == GateResult.DEFERRED:
            plan.status = RetirementPlanStatus.PASSED
            plan.save(update_fields=["status", "updated_at"])
        return plan
