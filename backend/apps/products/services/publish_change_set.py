"""Atomic publication of approved product change sets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import DatabaseError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
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
    ChannelConfiguration,
    ChannelStatus,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductVersion,
    ProductVersionScope,
    ProductVersionStatus,
    SKUStatus,
    VersionScopeStatus,
    VersionScopeType,
)
from apps.products.services.validate_publication import ValidateProductPublication


@dataclass(frozen=True)
class ProductPublicationResult:
    change_set: ProductChangeSet
    product_version: ProductVersion


def create_channel_configurations(
    *, change_set: ProductChangeSet, product_version: ProductVersion
) -> None:
    """Create channel configurations declared on the change set scope."""
    from apps.platform.api.errors import ValidationFailedError

    scope = change_set.change_scope or {}
    channels = scope.get("channels")
    if not isinstance(channels, list) or not channels:
        return

    sku_by_code = {sku.sku_code: sku for sku in SKU.objects.filter(product_version=product_version)}
    for index, row in enumerate(channels):
        if not isinstance(row, dict):
            raise ValidationFailedError(
                details={"blocks": ["PRODUCT_CHANNEL_INVALID"], "index": index},
            )
        sku_code = str(row.get("sku_code") or "").strip()
        channel_code = str(row.get("channel_code") or "").strip()
        if not sku_code or not channel_code:
            raise ValidationFailedError(
                details={"blocks": ["PRODUCT_CHANNEL_INCOMPLETE"], "index": index},
            )
        sku = sku_by_code.get(sku_code)
        if sku is None:
            raise ValidationFailedError(
                details={
                    "blocks": ["PRODUCT_CHANNEL_SKU_UNKNOWN"],
                    "sku_code": sku_code,
                    "channel_code": channel_code,
                },
            )
        ChannelConfiguration.objects.create(
            organization=change_set.organization,
            sku=sku,
            channel_code=channel_code,
            configuration_version=1,
            channel_status=str(row.get("channel_status") or ChannelStatus.ON_SALE),
            channel_selling_points=str(row.get("channel_selling_points") or ""),
            change_set=change_set,
            valid_from=product_version.effective_from,
        )


def _publish_skus_and_scopes(
    *,
    change_set: ProductChangeSet,
    product_version: ProductVersion,
) -> None:
    scope = change_set.change_scope or {}
    sku_rows = scope.get("skus")
    if isinstance(sku_rows, list) and sku_rows:
        for row in sku_rows:
            if not isinstance(row, dict):
                continue
            sku_code = str(row.get("sku_code") or "")
            if not sku_code:
                continue
            create_iteration_sku(
                change_set=change_set,
                product_version=product_version,
                sku_code=sku_code,
                name=str(row.get("name") or change_set.product.name),
                specification=str(row.get("specification") or ""),
                barcode=str(row.get("barcode") or ""),
            )
    elif change_set.change_type == ChangeSetType.NEW_PRODUCT:
        create_iteration_sku(
            change_set=change_set,
            product_version=product_version,
            sku_code=f"SKU-{change_set.product.business_no}",
            name=change_set.product.name,
        )

    scope_rows = scope.get("scopes")
    if isinstance(scope_rows, list) and scope_rows:
        for row in scope_rows:
            if not isinstance(row, dict):
                continue
            ProductVersionScope.objects.create(
                organization=change_set.organization,
                product_version=product_version,
                scope_type=str(row.get("scope_type") or VersionScopeType.GLOBAL),
                channel_code=str(row.get("channel_code") or ""),
                status=str(row.get("status") or VersionScopeStatus.EFFECTIVE),
                valid_from=product_version.effective_from,
            )
    else:
        ProductVersionScope.objects.create(
            organization=change_set.organization,
            product_version=product_version,
            scope_type=VersionScopeType.GLOBAL,
            status=VersionScopeStatus.EFFECTIVE,
            valid_from=product_version.effective_from,
        )


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
                _publish_skus_and_scopes(change_set=change_set, product_version=product_version)
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
        actor: User,
        now: datetime,
    ) -> ProductVersion:
        version_code = self._next_version_code(change_set.product_id)
        scope = change_set.change_scope or {}
        effective_from = now
        raw_effective = scope.get("effective_from")
        if raw_effective:
            effective_from = datetime.fromisoformat(str(raw_effective).replace("Z", "+00:00"))
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
            effective_from=effective_from,
        )

    def _next_version_code(self, product_id: int) -> str:
        count = ProductVersion.objects.filter(product_id=product_id).count()
        return f"V{count + 1}"

    def _activate_attribute_snapshots(self, *, change_set: ProductChangeSet, now: datetime) -> None:
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
    specification: str = "",
    barcode: str = "",
) -> SKU:
    return SKU.objects.create(
        organization=change_set.organization,
        product_version=product_version,
        sku_code=sku_code,
        name=name,
        specification=specification,
        barcode=barcode,
        status=SKUStatus.ACTIVE,
        effective_from=product_version.effective_from,
    )
