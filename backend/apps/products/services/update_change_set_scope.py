"""Update SKU, channel and scope payloads on a product change set."""

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
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
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
    effective_from: str | None = None

    def execute(self) -> ProductChangeSet:
        actor = self.context.actor
        now = self.context.occurred_at

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
            if self.effective_from is not None:
                scope["effective_from"] = self.effective_from
            change_set.change_scope = scope
            change_set.version_no += 1
            change_set.save(update_fields=["change_scope", "version_no", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_draft.edit_group",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "version_no": change_set.version_no,
                        "scope_keys": sorted(scope),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="product_change_set.scope_updated",
                    aggregate_type="product_change_set",
                    aggregate_id=change_set.public_id,
                    payload={
                        "change_set_public_id": str(change_set.public_id),
                        "version_no": change_set.version_no,
                    },
                    occurred_at=now,
                )
            )

        return change_set
