"""Atomic publication of approved product change sets."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import DatabaseError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.errors import ChangeSetAlreadyPublished, ProductPublicationFailed
from apps.products.models import (
    SKU,
    AttributeGroupValue,
    AttributeValueStatus,
    ChangeSetStatus,
    ChangeSetType,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)
from apps.products.services.validate_publication import ValidateProductPublication


@dataclass(frozen=True)
class ProductPublicationResult:
    change_set: ProductChangeSet
    product_version: ProductVersion


def create_channel_configurations(
    *, change_set: ProductChangeSet, product_version: ProductVersion
) -> None:
    """Hook for channel configuration creation during publication."""
    del change_set, product_version


@dataclass
class PublishProductChangeSet:
    context: CommandContext
    change_set_public_id: UUID
    idempotency_key: str

    def execute(self) -> ProductPublicationResult:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            change_set = (
                ProductChangeSet.objects.select_for_update()
                .select_related("product", "base_version")
                .filter(
                    public_id=self.change_set_public_id,
                    organization_id=actor.organization_id,
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
                    return ProductPublicationResult(
                        change_set=change_set,
                        product_version=existing_version,
                    )
                raise ChangeSetAlreadyPublished()

            decision = authorize(
                subject_for(actor),
                action="product.publish_new"
                if change_set.change_type == ChangeSetType.NEW_PRODUCT
                else "product.publish_iteration",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=change_set.product.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            validation = ValidateProductPublication(
                actor=actor,
                change_set_public_id=change_set.public_id,
            ).execute()
            if not validation.can_publish:
                from apps.platform.api.errors import ValidationFailedError

                raise ValidationFailedError(
                    details={"blocks": [block.code for block in validation.blocks]},
                )

            try:
                product_version = self._publish_version(change_set=change_set, actor=actor, now=now)
                create_channel_configurations(
                    change_set=change_set, product_version=product_version
                )
                self._activate_attribute_snapshots(change_set=change_set, now=now)
            except DatabaseError as exc:
                raise ProductPublicationFailed() from exc

            product = change_set.product
            if change_set.change_type == ChangeSetType.NEW_PRODUCT:
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
                    action_code="product.publish_new",
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
                    event_type="product_version.published",
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

        return ProductPublicationResult(change_set=change_set, product_version=product_version)

    def _publish_version(
        self,
        *,
        change_set: ProductChangeSet,
        actor,
        now,
    ) -> ProductVersion:
        version_code = self._next_version_code(change_set.product_id)
        return ProductVersion.objects.create(
            organization=change_set.organization,
            product=change_set.product,
            version_code=version_code,
            version_name=change_set.title,
            status=ProductVersionStatus.EFFECTIVE,
            change_set=change_set,
            definition_summary=change_set.definition_summary,
            published_at=now,
            published_by=actor,
            effective_from=now,
        )

    def _next_version_code(self, product_id: int) -> str:
        count = ProductVersion.objects.filter(product_id=product_id).count()
        return f"V{count + 1}"

    def _activate_attribute_snapshots(self, *, change_set: ProductChangeSet, now) -> None:
        AttributeGroupValue.objects.filter(change_set=change_set).update(
            value_status=AttributeValueStatus.EFFECTIVE,
            updated_at=now,
        )


def create_iteration_sku(
    *,
    change_set: ProductChangeSet,
    product_version: ProductVersion,
    sku_code: str,
    name: str,
) -> SKU:
    return SKU.objects.create(
        organization=change_set.organization,
        product_version=product_version,
        sku_code=sku_code,
        name=name,
        status=SKUStatus.ACTIVE,
        effective_from=product_version.effective_from,
    )
