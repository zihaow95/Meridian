"""Publish legacy baseline change sets as active product dossiers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import DatabaseError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.errors import ChangeSetAlreadyPublished, ProductPublicationFailed
from apps.products.models import (
    SKU,
    ChangeSetStatus,
    ChangeSetType,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)


@dataclass(frozen=True)
class LegacyBaselinePublicationResult:
    change_set: ProductChangeSet
    product_version: ProductVersion


@dataclass
class PublishLegacyBaseline:
    context: CommandContext
    baseline_public_id: UUID
    idempotency_key: str = "legacy-baseline-publish"

    def execute(self) -> LegacyBaselinePublicationResult:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            change_set = (
                ProductChangeSet.objects.select_for_update()
                .select_related("product")
                .filter(
                    public_id=self.baseline_public_id,
                    organization_id=actor.organization_id,
                    change_type=ChangeSetType.LEGACY_BASELINE,
                )
                .first()
            )
            if change_set is None:
                raise PermissionDeniedError()

            existing_version = ProductVersion.objects.filter(change_set=change_set).first()
            if change_set.status == ChangeSetStatus.PUBLISHED:
                if (
                    change_set.publish_idempotency_key == self.idempotency_key
                    and existing_version is not None
                ):
                    return LegacyBaselinePublicationResult(
                        change_set=change_set,
                        product_version=existing_version,
                    )
                raise ChangeSetAlreadyPublished()

            decision = authorize(
                subject_for(actor),
                action="product.publish_baseline",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=change_set.product.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            payload = _import_payload(change_set)
            if not payload.get("name"):
                raise ValidationFailedError(details={"blocks": ["PRODUCT_REQUIRED_FIELD_MISSING"]})

            try:
                product_version = ProductVersion.objects.create(
                    organization=change_set.organization,
                    product=change_set.product,
                    version_code="V1",
                    version_name=change_set.title,
                    status=ProductVersionStatus.EFFECTIVE,
                    change_set=change_set,
                    definition_summary=change_set.definition_summary,
                    published_at=now,
                    published_by=actor,
                    effective_from=now,
                )
                self._create_sku(
                    change_set=change_set,
                    product_version=product_version,
                    payload=payload,
                )
            except DatabaseError as exc:
                raise ProductPublicationFailed() from exc

            product = change_set.product
            product.lifecycle_status = ProductLifecycleStatus.ACTIVE
            product.primary_version = product_version
            product.save(update_fields=["lifecycle_status", "primary_version", "updated_at"])

            change_set.status = ChangeSetStatus.PUBLISHED
            change_set.published_at = now
            change_set.publish_idempotency_key = self.idempotency_key
            change_set.approved_by = actor
            change_set.save(
                update_fields=[
                    "status",
                    "published_at",
                    "publish_idempotency_key",
                    "approved_by",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product.publish_baseline",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "product_version_public_id": str(product_version.public_id),
                        "idempotency_key": self.idempotency_key,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="legacy_baseline.published",
                    aggregate_type="product",
                    aggregate_id=product.public_id,
                    payload={
                        "product_public_id": str(product.public_id),
                        "product_version_public_id": str(product_version.public_id),
                        "change_set_public_id": str(change_set.public_id),
                    },
                    occurred_at=now,
                )
            )

        return LegacyBaselinePublicationResult(
            change_set=change_set,
            product_version=product_version,
        )

    def _create_sku(
        self,
        *,
        change_set: ProductChangeSet,
        product_version: ProductVersion,
        payload: dict[str, Any],
    ) -> SKU:
        net_value = None
        raw_net = payload.get("net_content_value")
        if raw_net:
            try:
                net_value = Decimal(str(raw_net))
            except InvalidOperation:
                net_value = None
        return SKU.objects.create(
            organization=change_set.organization,
            product_version=product_version,
            sku_code=str(payload.get("sku_code") or f"SKU-{change_set.product.business_no}"),
            name=str(payload.get("name") or change_set.product.name),
            specification=str(payload.get("specification") or ""),
            barcode=str(payload.get("barcode") or ""),
            net_content_value=net_value,
            net_content_unit=str(payload.get("net_content_unit") or ""),
            status=SKUStatus.ACTIVE,
            effective_from=product_version.effective_from,
        )


def _import_payload(change_set: ProductChangeSet) -> dict[str, Any]:
    scope = change_set.change_scope or {}
    payload = scope.get("payload")
    if isinstance(payload, dict):
        return payload
    return {}
