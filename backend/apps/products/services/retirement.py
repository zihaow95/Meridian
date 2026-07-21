"""Product-domain retirement state transitions owned by products."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    SKU,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductionStatus,
    ProductLifecycleStatus,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)


@dataclass
class ApplyApprovedRetirementAction:
    context: CommandContext
    action_type: str
    product_public_id: UUID
    scope_snapshot: dict
    as_of: date

    def execute(self) -> None:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            product = (
                ProductAsset.objects.select_for_update()
                .filter(organization_id=actor.organization_id, public_id=self.product_public_id)
                .first()
            )
            if product is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="retirement_plan.execute",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=product.public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                # Execution is system/ops driven; allow when actor has retirement_plan.execute
                # on retirement_plan resource as fallback.
                decision = authorize(
                    subject_for(actor),
                    action="retirement_plan.execute",
                    resource=ResourceDescriptor(
                        resource_type="retirement_plan",
                        public_id=None,
                        organization_id=actor.organization_id,
                        metadata={"product_public_id": str(product.public_id)},
                    ),
                    context=AuthorizationContext.current(),
                )
                if not decision.allowed:
                    raise PermissionDeniedError()

            version_ids = [
                UUID(str(v)) for v in (self.scope_snapshot.get("product_version_public_ids") or [])
            ]
            sku_ids = [UUID(str(v)) for v in (self.scope_snapshot.get("sku_public_ids") or [])]
            channel_ids = [
                UUID(str(v)) for v in (self.scope_snapshot.get("channel_public_ids") or [])
            ]
            if not version_ids or not sku_ids:
                raise ValidationFailedError(message="Retirement scope requires versions and SKUs.")

            if self.action_type == "STOP_PRODUCTION":
                skus = list(
                    SKU.objects.select_for_update().filter(
                        organization_id=actor.organization_id,
                        public_id__in=sku_ids,
                        product_version__product=product,
                    )
                )
                for sku in skus:
                    if sku.production_status == ProductionStatus.STOPPED:
                        continue
                    sku.production_status = ProductionStatus.STOPPED
                    sku.production_stopped_at = now
                    sku.save(
                        update_fields=[
                            "production_status",
                            "production_stopped_at",
                            "updated_at",
                        ]
                    )
            elif self.action_type == "STOP_SALE":
                channels = list(
                    ChannelConfiguration.objects.select_for_update().filter(
                        organization_id=actor.organization_id,
                        public_id__in=channel_ids,
                        sku__product_version__product=product,
                    )
                )
                for channel in channels:
                    if channel.channel_status == ChannelStatus.OFF_SALE:
                        continue
                    channel.channel_status = ChannelStatus.OFF_SALE
                    channel.valid_to = now
                    channel.save(update_fields=["channel_status", "valid_to", "updated_at"])
            elif self.action_type == "RETIRE":
                skus = list(
                    SKU.objects.select_for_update().filter(
                        organization_id=actor.organization_id,
                        public_id__in=sku_ids,
                        product_version__product=product,
                    )
                )
                for sku in skus:
                    sku.status = SKUStatus.INACTIVE
                    sku.effective_to = now
                    if sku.production_status != ProductionStatus.STOPPED:
                        sku.production_status = ProductionStatus.STOPPED
                        sku.production_stopped_at = now
                    sku.save(
                        update_fields=[
                            "status",
                            "effective_to",
                            "production_status",
                            "production_stopped_at",
                            "updated_at",
                        ]
                    )
                versions = list(
                    ProductVersion.objects.select_for_update().filter(
                        organization_id=actor.organization_id,
                        public_id__in=version_ids,
                        product=product,
                    )
                )
                for version in versions:
                    version.status = ProductVersionStatus.INACTIVE
                    version.effective_to = now
                    version.save(update_fields=["status", "effective_to", "updated_at"])
                if product.lifecycle_status != ProductLifecycleStatus.RETIRED:
                    product.lifecycle_status = ProductLifecycleStatus.RETIRED
                    product.retired_at = now
                    product.save(
                        update_fields=["lifecycle_status", "retired_at", "updated_at"]
                    )
            else:
                raise ValidationFailedError(
                    message=f"Unknown retirement action: {self.action_type}"
                )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="retirement_plan.execute",
                    resource_type="product",
                    resource_public_id=product.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "action_type": self.action_type,
                        "as_of": self.as_of.isoformat(),
                    },
                )
            )
