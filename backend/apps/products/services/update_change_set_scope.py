"""Update SKU, channel and scope payloads on a product change set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.errors import ChangeSetNotEditable, ChangeSetVersionConflict
from apps.products.models import ChangeSetStatus, ProductChangeSet


@dataclass
class UpdateProductChangeSetScope:
    context: CommandContext
    change_set_public_id: UUID
    version_no: int
    skus: list[dict[str, Any]] | None = None
    channels: list[dict[str, Any]] | None = None
    scopes: list[dict[str, Any]] | None = None

    def execute(self) -> ProductChangeSet:
        actor = self.context.actor

        with transaction.atomic():
            change_set = (
                ProductChangeSet.objects.select_for_update()
                .select_related("product")
                .filter(
                    public_id=self.change_set_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if change_set is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="product_draft.edit_group",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=change_set.product.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if change_set.status not in {ChangeSetStatus.DRAFT, ChangeSetStatus.IN_CONFIRMATION}:
                raise ChangeSetNotEditable()

            if change_set.version_no != self.version_no:
                raise ChangeSetVersionConflict()

            scope = dict(change_set.change_scope or {})
            if self.skus is not None:
                scope["skus"] = self.skus
            if self.channels is not None:
                scope["channels"] = self.channels
            if self.scopes is not None:
                scope["scopes"] = self.scopes
            change_set.change_scope = scope
            change_set.version_no += 1
            change_set.save(update_fields=["change_scope", "version_no", "updated_at"])

        return change_set
