"""Operating issue creation, escalation, decisions, and transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.errors import IssueImmutableState, IssueVersionConflict
from apps.operations.models import (
    IssueDecision,
    IssueSignal,
    IssueSourceType,
    OperatingDataSnapshot,
    OperatingIssue,
    OperatingIssueStatus,
    RecommendationType,
    RiskSignal,
    RiskSignalStatus,
)
from apps.operations.policies.identity_provider import resolve_effective_assignments
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import SKU, ProductAsset

_IMMUTABLE_STATUSES = frozenset(
    {
        OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
        OperatingIssueStatus.RETIREMENT_REVIEW,
    }
)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    OperatingIssueStatus.PENDING: frozenset({OperatingIssueStatus.ANALYZING}),
    OperatingIssueStatus.ANALYZING: frozenset(
        {
            OperatingIssueStatus.OBSERVING,
            OperatingIssueStatus.ACTIONING,
            OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
            OperatingIssueStatus.RETIREMENT_REVIEW,
            OperatingIssueStatus.CLOSED,
        }
    ),
    OperatingIssueStatus.OBSERVING: frozenset({OperatingIssueStatus.ANALYZING}),
    OperatingIssueStatus.ACTIONING: frozenset({OperatingIssueStatus.ANALYZING}),
}


def _not_found() -> PermissionDeniedError:
    return PermissionDeniedError()


def _authorize_issue_action(*, actor: User, action: str, issue: OperatingIssue) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="operating_issue",
            public_id=issue.public_id,
            organization_id=actor.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={"product_public_id": str(issue.product.public_id)},
        ),
        context=AuthorizationContext.current(),
    )
    if decision.allowed:
        return

    assignments = resolve_effective_assignments(user=actor, organization_id=actor.organization_id)
    required = DataSensitivityLevel.SENSITIVE_CONTROLLED
    for assignment in assignments:
        if assignment.product_id != issue.product_id:
            continue
        if LEVEL_RANK.get(assignment.max_data_level, 0) < LEVEL_RANK.get(required, 0):
            continue
        return
    raise _not_found()


def _authorize_create(*, actor: User, product: ProductAsset) -> None:
    decision = authorize(
        subject_for(actor),
        action="operating_issue.create",
        resource=ResourceDescriptor(
            resource_type="operating_issue",
            public_id=None,
            organization_id=actor.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            metadata={"product_public_id": str(product.public_id)},
        ),
        context=AuthorizationContext.current(),
    )
    if decision.allowed:
        return

    assignments = resolve_effective_assignments(user=actor, organization_id=actor.organization_id)
    required = DataSensitivityLevel.SENSITIVE_CONTROLLED
    for assignment in assignments:
        if assignment.product_id != product.id:
            continue
        if LEVEL_RANK.get(assignment.max_data_level, 0) < LEVEL_RANK.get(required, 0):
            continue
        return
    raise _not_found()


def _issue_or_deny(*, organization_id: int, issue_public_id: UUID) -> OperatingIssue:
    issue = (
        OperatingIssue.objects.select_related("product", "owner", "data_snapshot")
        .filter(organization_id=organization_id, public_id=issue_public_id)
        .first()
    )
    if issue is None:
        raise _not_found()
    return issue


def _create_issue_snapshot(
    *,
    organization_id: int,
    actor: User,
    product: ProductAsset,
    signals: list[RiskSignal],
    source_type: str,
) -> OperatingDataSnapshot:
    scope_json = {
        "product_public_id": str(product.public_id),
        "signal_public_ids": [str(s.public_id) for s in signals],
        "source_type": source_type,
    }
    payload_json = {
        "scope": scope_json,
        "signals": [
            {
                "signal_public_id": str(s.public_id),
                "scope_key": s.scope_key,
                "period_start": s.period_start.isoformat(),
                "period_end": s.period_end.isoformat(),
                "actual_value": str(s.actual_value) if s.actual_value is not None else None,
                "threshold_value": (
                    str(s.threshold_value) if s.threshold_value is not None else None
                ),
                "status": s.status,
            }
            for s in signals
        ],
    }
    snapshot = OperatingDataSnapshot(
        organization_id=organization_id,
        purpose="operating_issue",
        scope_json=scope_json,
        periods_json=[],
        metric_codes=[],
        payload_json=payload_json,
        created_by=actor,
    )
    snapshot.content_hash = snapshot.compute_content_hash()
    snapshot.save()
    return snapshot


def _clear_primary_links(*, issue: OperatingIssue, now: datetime) -> None:
    links = list(IssueSignal.objects.select_for_update().filter(issue=issue, active_primary_slot=1))
    for link in links:
        link.active_primary_slot = None
        link.unlinked_at = now
        link.save(update_fields=["active_primary_slot", "unlinked_at", "updated_at"])


def _link_signals(
    *,
    organization_id: int,
    issue: OperatingIssue,
    signals: list[RiskSignal],
    now: datetime,
) -> None:
    for index, signal in enumerate(signals):
        is_primary = index == 0
        try:
            IssueSignal.objects.create(
                organization_id=organization_id,
                issue=issue,
                signal=signal,
                is_primary=is_primary,
                active_primary_slot=1 if is_primary else None,
                linked_at=now,
            )
        except IntegrityError as exc:
            raise ValidationFailedError(
                message="Signal already has an active primary operating issue."
            ) from exc
        if signal.status in {RiskSignalStatus.NEW, RiskSignalStatus.VIEWED}:
            signal.status = RiskSignalStatus.ESCALATED
            signal.save(update_fields=["status", "updated_at"])


@dataclass
class CreateOperatingIssue:
    context: CommandContext
    title: str
    product_public_id: UUID
    phenomenon_summary: str
    signal_public_ids: list[UUID] = field(default_factory=list)
    source_type: str = IssueSourceType.RISK_SIGNAL
    source_materials_json: dict[str, Any] | None = None
    target_review_at: datetime | None = None
    owner_public_id: UUID | None = None

    def execute(self) -> OperatingIssue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        title = (self.title or "").strip()
        summary = (self.phenomenon_summary or "").strip()
        if not title or not summary:
            raise ValidationFailedError(message="title and phenomenon_summary are required.")

        with transaction.atomic():
            product = ProductAsset.objects.filter(
                organization_id=actor.organization_id, public_id=self.product_public_id
            ).first()
            if product is None:
                raise _not_found()
            _authorize_create(actor=actor, product=product)

            signals: list[RiskSignal] = []
            if self.signal_public_ids:
                signals = list(
                    RiskSignal.objects.select_for_update()
                    .filter(
                        organization_id=actor.organization_id,
                        public_id__in=self.signal_public_ids,
                    )
                    .order_by("created_at", "id")
                )
                if len(signals) != len(set(self.signal_public_ids)):
                    raise ValidationFailedError(message="One or more signals were not found.")
                self.source_type = IssueSourceType.RISK_SIGNAL
            else:
                if self.source_type == IssueSourceType.RISK_SIGNAL:
                    raise ValidationFailedError(
                        message="signal_public_ids or a non-signal source_type is required."
                    )
                materials = self.source_materials_json or {}
                if not materials:
                    raise ValidationFailedError(
                        message="source_materials_json is required for non-signal sources."
                    )

            owner = actor
            if self.owner_public_id is not None:
                resolved_owner = User.objects.filter(
                    organization_id=actor.organization_id, public_id=self.owner_public_id
                ).first()
                if resolved_owner is None:
                    raise ValidationFailedError(message="Owner not found.")
                owner = resolved_owner

            snapshot = _create_issue_snapshot(
                organization_id=actor.organization_id,
                actor=actor,
                product=product,
                signals=signals,
                source_type=self.source_type,
            )
            issue = OperatingIssue.objects.create(
                organization_id=actor.organization_id,
                business_no=f"ISS-{uuid4().hex[:8].upper()}",
                title=title,
                product=product,
                status=OperatingIssueStatus.PENDING,
                owner=owner,
                source_type=self.source_type,
                source_materials_json=dict(self.source_materials_json or {}),
                phenomenon_summary=summary,
                data_snapshot=snapshot,
                target_review_at=self.target_review_at,
                created_by=actor,
            )
            if signals:
                _link_signals(
                    organization_id=actor.organization_id,
                    issue=issue,
                    signals=signals,
                    now=now,
                )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="operating_issue.create",
                    resource_type="operating_issue",
                    resource_public_id=issue.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={
                        "business_no": issue.business_no,
                        "signal_count": len(signals),
                        "source_type": issue.source_type,
                    },
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="operating_issue.created",
                    aggregate_type="operating_issue",
                    aggregate_id=issue.public_id,
                    payload={
                        "issue_public_id": str(issue.public_id),
                        "organization_id": issue.organization_id,
                        "owner_id": issue.owner_id,
                        "target_review_at": (
                            issue.target_review_at.isoformat() if issue.target_review_at else None
                        ),
                        "title": issue.title,
                    },
                    occurred_at=now,
                )
            )
            return issue


@dataclass
class EscalateRiskSignal:
    context: CommandContext
    signal_public_id: UUID
    title: str
    phenomenon_summary: str
    target_review_at: datetime | None = None

    def execute(self) -> OperatingIssue:
        actor = self.context.actor
        with transaction.atomic():
            signal = (
                RiskSignal.objects.select_for_update()
                .select_related("channel")
                .filter(organization_id=actor.organization_id, public_id=self.signal_public_id)
                .first()
            )
            if signal is None:
                raise _not_found()
            sku = (
                SKU.objects.filter(public_id=signal.scope_id)
                .select_related("product_version__product")
                .first()
            )
            if sku is None:
                raise ValidationFailedError(message="Signal scope SKU not found.")
            product = sku.product_version.product
            decision = authorize(
                subject_for(actor),
                action="risk_signal.escalate",
                resource=ResourceDescriptor(
                    resource_type="risk_signal",
                    public_id=signal.public_id,
                    organization_id=actor.organization_id,
                    sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
                    metadata={
                        "product_public_id": str(product.public_id),
                        "sku_public_id": str(sku.public_id),
                        "channel_public_id": (
                            str(signal.channel.public_id) if signal.channel is not None else None
                        ),
                    },
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                assignments = resolve_effective_assignments(
                    user=actor, organization_id=actor.organization_id
                )
                required = DataSensitivityLevel.SENSITIVE_CONTROLLED
                covered = False
                for assignment in assignments:
                    if assignment.product_id != product.id:
                        continue
                    if LEVEL_RANK.get(assignment.max_data_level, 0) < LEVEL_RANK.get(required, 0):
                        continue
                    covered = True
                    break
                if not covered:
                    raise _not_found()
            return CreateOperatingIssue(
                context=self.context,
                title=self.title,
                product_public_id=product.public_id,
                phenomenon_summary=self.phenomenon_summary,
                signal_public_ids=[signal.public_id],
                target_review_at=self.target_review_at,
            ).execute()


@dataclass
class RecordOperatingIssueDecision:
    context: CommandContext
    issue_public_id: UUID
    version_no: int
    recommendation_type: str
    action_summary: str
    responsible_user_public_id: UUID | None = None
    planned_at: datetime | None = None
    materials_snapshot_json: dict[str, Any] | None = None
    target_status: str | None = None

    def execute(self) -> IssueDecision:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        summary = (self.action_summary or "").strip()
        if not summary:
            raise ValidationFailedError(message="action_summary is required.")
        if self.recommendation_type not in RecommendationType.values:
            raise ValidationFailedError(message="Unknown recommendation_type.")

        with transaction.atomic():
            issue = (
                OperatingIssue.objects.select_for_update()
                .select_related("product")
                .filter(organization_id=actor.organization_id, public_id=self.issue_public_id)
                .first()
            )
            if issue is None:
                raise _not_found()
            _authorize_issue_action(actor=actor, action="operating_issue.analyze", issue=issue)
            if issue.version_no != self.version_no:
                raise IssueVersionConflict()
            if issue.status in _IMMUTABLE_STATUSES:
                raise IssueImmutableState()

            responsible = None
            if self.responsible_user_public_id is not None:
                from apps.identity.models.user import User

                responsible = User.objects.filter(
                    organization_id=actor.organization_id,
                    public_id=self.responsible_user_public_id,
                ).first()
                if responsible is None:
                    raise ValidationFailedError(message="Responsible user not found.")

            decision = IssueDecision.objects.create(
                organization_id=actor.organization_id,
                issue=issue,
                recommendation_type=self.recommendation_type,
                action_summary=summary,
                responsible_user=responsible,
                planned_at=self.planned_at,
                materials_snapshot_json=dict(self.materials_snapshot_json or {}),
                decided_by=actor,
                decided_at=now,
            )
            issue.recommendation_type = self.recommendation_type
            issue.version_no += 1
            update_fields = ["recommendation_type", "version_no", "updated_at"]

            next_status = self.target_status
            if next_status is None:
                if self.recommendation_type == RecommendationType.CONTINUE_OBSERVING:
                    next_status = OperatingIssueStatus.OBSERVING
                elif self.recommendation_type == RecommendationType.CLOSE:
                    next_status = OperatingIssueStatus.CLOSED
                elif self.recommendation_type == RecommendationType.RETIRE:
                    next_status = OperatingIssueStatus.RETIREMENT_REVIEW
                elif self.recommendation_type == RecommendationType.ITERATE:
                    next_status = OperatingIssueStatus.ACTIONING
                elif issue.status == OperatingIssueStatus.PENDING:
                    next_status = OperatingIssueStatus.ANALYZING
                else:
                    next_status = OperatingIssueStatus.ACTIONING

            if next_status != issue.status:
                allowed = _ALLOWED_TRANSITIONS.get(issue.status, frozenset())
                # Allow first decision from PENDING to move via ANALYZING then target.
                if (
                    issue.status == OperatingIssueStatus.PENDING
                    and next_status != OperatingIssueStatus.ANALYZING
                ):
                    issue.status = OperatingIssueStatus.ANALYZING
                    update_fields.append("status")
                if next_status != issue.status:
                    if issue.status == OperatingIssueStatus.ANALYZING and next_status in {
                        OperatingIssueStatus.OBSERVING,
                        OperatingIssueStatus.ACTIONING,
                        OperatingIssueStatus.RETIREMENT_REVIEW,
                        OperatingIssueStatus.CLOSED,
                        OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
                    }:
                        issue.status = next_status
                        if "status" not in update_fields:
                            update_fields.append("status")
                    elif next_status not in allowed and next_status != issue.status:
                        raise ValidationFailedError(
                            message=f"Cannot transition from {issue.status} to {next_status}."
                        )
                    else:
                        issue.status = next_status
                        if "status" not in update_fields:
                            update_fields.append("status")

            if issue.status == OperatingIssueStatus.CLOSED:
                issue.closed_at = now
                issue.closed_by = actor
                update_fields.extend(["closed_at", "closed_by"])
                _clear_primary_links(issue=issue, now=now)

            issue.save(update_fields=update_fields)
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="operating_issue.analyze",
                    resource_type="operating_issue",
                    resource_public_id=issue.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={"version_no": self.version_no},
                    after_summary={
                        "recommendation_type": self.recommendation_type,
                        "status": issue.status,
                        "version_no": issue.version_no,
                    },
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="operating_issue.decided",
                    aggregate_type="operating_issue",
                    aggregate_id=issue.public_id,
                    payload={
                        "issue_public_id": str(issue.public_id),
                        "decision_public_id": str(decision.public_id),
                        "recommendation_type": self.recommendation_type,
                        "responsible_user_id": (
                            responsible.id if responsible is not None else None
                        ),
                        "planned_at": self.planned_at.isoformat() if self.planned_at else None,
                        "title": issue.title,
                    },
                    occurred_at=now,
                )
            )
            return decision


@dataclass
class TransitionOperatingIssue:
    context: CommandContext
    issue_public_id: UUID
    version_no: int
    target_status: str

    def execute(self) -> OperatingIssue:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            issue = (
                OperatingIssue.objects.select_for_update()
                .select_related("product")
                .filter(organization_id=actor.organization_id, public_id=self.issue_public_id)
                .first()
            )
            if issue is None:
                raise _not_found()
            action = (
                "operating_issue.close"
                if self.target_status == OperatingIssueStatus.CLOSED
                else "operating_issue.analyze"
            )
            _authorize_issue_action(actor=actor, action=action, issue=issue)
            if issue.version_no != self.version_no:
                raise IssueVersionConflict()
            if issue.status in _IMMUTABLE_STATUSES and self.target_status not in {issue.status}:
                # Converted / retirement review cannot be deleted or reset arbitrarily.
                if self.target_status == OperatingIssueStatus.CLOSED:
                    raise IssueImmutableState(
                        message="Converted or retirement-review issues cannot be closed away."
                    )
                raise IssueImmutableState()

            allowed = _ALLOWED_TRANSITIONS.get(issue.status, frozenset())
            if self.target_status not in allowed and self.target_status != issue.status:
                raise ValidationFailedError(
                    message=f"Cannot transition from {issue.status} to {self.target_status}."
                )
            if self.target_status == issue.status:
                return issue

            previous = issue.status
            issue.status = self.target_status
            issue.version_no += 1
            update_fields = ["status", "version_no", "updated_at"]
            if self.target_status == OperatingIssueStatus.CLOSED:
                issue.closed_at = now
                issue.closed_by = actor
                update_fields.extend(["closed_at", "closed_by"])
                _clear_primary_links(issue=issue, now=now)
            issue.save(update_fields=update_fields)
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code=action,
                    resource_type="operating_issue",
                    resource_public_id=issue.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={"status": previous, "version_no": self.version_no},
                    after_summary={"status": issue.status, "version_no": issue.version_no},
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            return issue
