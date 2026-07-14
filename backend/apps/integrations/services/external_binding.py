"""Manage external system bindings for product objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.integrations.models import BindingStatus, ExternalBinding
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.errors import ExternalBindingConflict
from apps.products.models import ProductAsset


@dataclass(frozen=True)
class ExternalBindingInput:
    source_system: str
    object_type: str
    external_id: str
    internal_object_type: str
    internal_object_id: int
    source_timestamp: datetime | None = None


@dataclass
class UpsertExternalBinding:
    context: CommandContext
    product_public_id: UUID
    binding: ExternalBindingInput

    def execute(self) -> ExternalBinding:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            product = (
                ProductAsset.objects.select_for_update()
                .filter(
                    public_id=self.product_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if product is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="external_binding.manage",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=product.public_id,
                    organization_id=product.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if (
                self.binding.internal_object_type != "product"
                or self.binding.internal_object_id != product.id
            ):
                raise PermissionDeniedError()

            conflict = (
                ExternalBinding.objects.select_for_update()
                .filter(
                    organization_id=product.organization_id,
                    source_system=self.binding.source_system,
                    object_type=self.binding.object_type,
                    external_id=self.binding.external_id,
                    binding_status=BindingStatus.ACTIVE,
                )
                .exclude(
                    internal_object_type=self.binding.internal_object_type,
                    internal_object_id=self.binding.internal_object_id,
                )
                .first()
            )
            if conflict is not None:
                raise ExternalBindingConflict()

            row, _created = ExternalBinding.objects.update_or_create(
                organization_id=product.organization_id,
                source_system=self.binding.source_system,
                object_type=self.binding.object_type,
                external_id=self.binding.external_id,
                defaults={
                    "internal_object_type": self.binding.internal_object_type,
                    "internal_object_id": self.binding.internal_object_id,
                    "source_timestamp": self.binding.source_timestamp,
                    "last_synced_at": self.binding.source_timestamp or now,
                    "binding_status": BindingStatus.ACTIVE,
                },
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="external_binding.manage",
                    resource_type="product",
                    resource_public_id=product.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "source_system": row.source_system,
                        "object_type": row.object_type,
                        "external_id": row.external_id,
                        "binding_public_id": str(row.public_id),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="external_binding.upserted",
                    aggregate_type="product",
                    aggregate_id=product.public_id,
                    payload={
                        "product_public_id": str(product.public_id),
                        "binding_public_id": str(row.public_id),
                        "source_system": row.source_system,
                        "external_id": row.external_id,
                    },
                    occurred_at=now,
                )
            )
        return row
