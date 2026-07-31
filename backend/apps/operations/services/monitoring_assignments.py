"""Assign and maintain monitoring supervisors within a monitoring scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    MonitoringScope,
    MonitoringScopeType,
    build_monitoring_scope_key,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import SKU, ChannelConfiguration, ProductAsset


@dataclass
class AssignMonitoringSupervisor:
    context: CommandContext
    monitoring_scope_public_id: UUID
    supervisor_public_id: UUID
    scope_type: str
    product_public_id: UUID
    sku_public_id: UUID | None = None
    channel_public_id: UUID | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    max_data_level: str = DataSensitivityLevel.SENSITIVE_CONTROLLED

    def execute(self) -> MonitoringAssignment:
        actor = self.context.actor
        now = self.context.occurred_at
        effective_from = self.effective_from or now

        with transaction.atomic():
            scope = (
                MonitoringScope.objects.select_for_update()
                .filter(
                    public_id=self.monitoring_scope_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if scope is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="monitoring_scope.manage",
                resource=ResourceDescriptor(
                    resource_type="monitoring_scope",
                    public_id=scope.public_id,
                    organization_id=scope.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            supervisor = User.objects.filter(
                public_id=self.supervisor_public_id,
                organization_id=actor.organization_id,
            ).first()
            if supervisor is None:
                raise PermissionDeniedError()

            product = ProductAsset.objects.filter(
                public_id=self.product_public_id,
                organization_id=actor.organization_id,
            ).first()
            if product is None:
                raise PermissionDeniedError()

            sku = None
            channel = None
            if self.scope_type == MonitoringScopeType.PRODUCT:
                if self.sku_public_id is not None or self.channel_public_id is not None:
                    raise ValidationFailedError(
                        message="PRODUCT scope must not set SKU or channel."
                    )
            elif self.scope_type == MonitoringScopeType.SKU:
                if self.sku_public_id is None or self.channel_public_id is not None:
                    raise ValidationFailedError(message="SKU scope requires sku only.")
                sku = SKU.objects.filter(
                    public_id=self.sku_public_id,
                    organization_id=actor.organization_id,
                ).first()
                if sku is None:
                    raise PermissionDeniedError()
            elif self.scope_type == MonitoringScopeType.SKU_CHANNEL:
                if self.sku_public_id is None or self.channel_public_id is None:
                    raise ValidationFailedError(
                        message="SKU_CHANNEL scope requires sku and channel."
                    )
                sku = SKU.objects.filter(
                    public_id=self.sku_public_id,
                    organization_id=actor.organization_id,
                ).first()
                channel = ChannelConfiguration.objects.filter(
                    public_id=self.channel_public_id,
                    organization_id=actor.organization_id,
                ).first()
                if sku is None or channel is None:
                    raise PermissionDeniedError()
            else:
                raise ValidationFailedError(message=f"Unknown scope_type: {self.scope_type}")

            scope_key = build_monitoring_scope_key(
                scope_type=self.scope_type,
                product_id=product.id,
                sku_id=sku.id if sku is not None else None,
                channel_id=channel.id if channel is not None else None,
            )

            existing = (
                MonitoringAssignment.objects.select_for_update()
                .filter(
                    monitoring_scope=scope,
                    supervisor=supervisor,
                    scope_key=scope_key,
                    active_slot=1,
                )
                .first()
            )
            if existing is not None:
                existing.effective_from = effective_from
                existing.effective_to = self.effective_to
                existing.max_data_level = self.max_data_level
                existing.status = MonitoringAssignmentStatus.ACTIVE
                existing.save(
                    update_fields=[
                        "effective_from",
                        "effective_to",
                        "max_data_level",
                        "status",
                        "updated_at",
                    ]
                )
                assignment = existing
            else:
                try:
                    assignment = MonitoringAssignment.objects.create(
                        organization=scope.organization,
                        monitoring_scope=scope,
                        supervisor=supervisor,
                        product=product,
                        sku=sku,
                        channel=channel,
                        scope_type=self.scope_type,
                        scope_key=scope_key,
                        effective_from=effective_from,
                        effective_to=self.effective_to,
                        status=MonitoringAssignmentStatus.ACTIVE,
                        active_slot=1,
                        max_data_level=self.max_data_level,
                    )
                except IntegrityError:
                    assignment = MonitoringAssignment.objects.get(
                        monitoring_scope=scope,
                        supervisor=supervisor,
                        scope_key=scope_key,
                        active_slot=1,
                    )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="monitoring_scope.manage",
                    resource_type="monitoring_scope",
                    resource_public_id=scope.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "assignment_public_id": str(assignment.public_id),
                        "supervisor_public_id": str(supervisor.public_id),
                        "scope_type": assignment.scope_type,
                        "scope_key": assignment.scope_key,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="monitoring_assignment.updated",
                    aggregate_type="monitoring_scope",
                    aggregate_id=scope.public_id,
                    payload={
                        "assignment_public_id": str(assignment.public_id),
                        "supervisor_public_id": str(supervisor.public_id),
                        "scope_key": assignment.scope_key,
                    },
                    occurred_at=now,
                )
            )
            return assignment
