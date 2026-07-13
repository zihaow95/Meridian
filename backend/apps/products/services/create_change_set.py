"""Create product change sets for new products and iterations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.products.models import (
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ChangeSetStatus,
    ChangeSetType,
    ProductAsset,
    ProductChangeSet,
    ProductVersion,
)
from apps.products.services.attribute_schema import compute_attribute_content_hash

_API_CHANGE_TYPES = frozenset({ChangeSetType.ITERATION, ChangeSetType.CORRECTION})


def compute_baseline_fingerprint(
    *, product: ProductAsset, base_version: ProductVersion | None
) -> str:
    payload: dict[str, Any] = {
        "product_id": product.id,
        "product_name": product.name,
        "base_version_id": base_version.id if base_version is not None else None,
    }
    if base_version is not None:
        payload["version_code"] = base_version.version_code
        payload["definition_summary"] = base_version.definition_summary
        baseline_values = AttributeGroupValue.objects.filter(
            organization_id=product.organization_id,
            owner_type=AttributeOwnerType.VERSION,
            owner_id=base_version.id,
            value_status=AttributeValueStatus.EFFECTIVE,
            change_set__isnull=True,
        ).select_related("group_definition")
        payload["attribute_groups"] = {
            row.group_definition.group_code: row.values_json for row in baseline_values
        }
    return compute_attribute_content_hash(payload)


def current_baseline_fingerprint(*, product: ProductAsset, base_version: ProductVersion) -> str:
    return compute_baseline_fingerprint(product=product, base_version=base_version)


def create_product_change_set_row(
    *,
    actor: User,
    product: ProductAsset,
    change_type: str,
    title: str,
    project_candidate_id: int | None = None,
    project_id: int | None = None,
    base_version: ProductVersion | None = None,
    definition_summary: str = "",
) -> ProductChangeSet:
    """Low-level change-set row create used by API and internal callers."""
    base_fingerprint = ""
    if change_type == ChangeSetType.ITERATION:
        if base_version is None:
            raise ValidationFailedError(message="Iteration change sets require a base version.")
        base_fingerprint = compute_baseline_fingerprint(
            product=product,
            base_version=base_version,
        )
    return ProductChangeSet.objects.create(
        organization=product.organization,
        change_type=change_type,
        status=ChangeSetStatus.DRAFT,
        product=product,
        base_version=base_version,
        base_fingerprint=base_fingerprint,
        project_candidate_id=project_candidate_id,
        project_id=project_id,
        title=title,
        definition_summary=definition_summary,
        created_by=actor,
    )


@dataclass
class CreateProductChangeSet:
    """API command: create an ITERATION or CORRECTION change set on an existing product."""

    context: CommandContext
    product_public_id: UUID
    change_type: str
    title: str | None = None
    base_version_public_id: UUID | None = None

    def execute(self) -> ProductChangeSet:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            product = (
                ProductAsset.objects.select_for_update()
                .select_related("primary_version", "source_project")
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
                action="product_draft.create",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=product.public_id,
                    organization_id=product.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if self.change_type not in _API_CHANGE_TYPES:
                raise ValidationFailedError(
                    message="change_type must be ITERATION or CORRECTION.",
                )

            base_version = self._resolve_base_version(product)
            title = (self.title or "").strip() or product.name

            change_set = create_product_change_set_row(
                actor=actor,
                product=product,
                change_type=self.change_type,
                title=title,
                project_candidate_id=None,
                project_id=product.source_project_id,
                base_version=base_version,
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_draft.create",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "change_type": change_set.change_type,
                        "product_public_id": str(product.public_id),
                        "base_version_public_id": (
                            str(base_version.public_id) if base_version is not None else None
                        ),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="product_change_set.created",
                    aggregate_type="product_change_set",
                    aggregate_id=change_set.public_id,
                    payload={
                        "change_set_public_id": str(change_set.public_id),
                        "product_public_id": str(product.public_id),
                        "change_type": change_set.change_type,
                    },
                    occurred_at=now,
                )
            )

        return change_set

    def _resolve_base_version(self, product: ProductAsset) -> ProductVersion | None:
        if self.base_version_public_id is not None:
            base_version = ProductVersion.objects.filter(
                public_id=self.base_version_public_id,
                product_id=product.id,
                organization_id=product.organization_id,
            ).first()
            if base_version is None:
                raise ValidationFailedError(
                    message="Base version was not found for this product.",
                )
            return base_version

        if self.change_type == ChangeSetType.ITERATION:
            if product.primary_version is None:
                raise ValidationFailedError(
                    message="Iteration change sets require a base version.",
                )
            return product.primary_version

        return None
