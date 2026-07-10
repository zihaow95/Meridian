"""Edit attribute group values on a product change set."""

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
from apps.products.models import (
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ChangeSetStatus,
    ProductChangeSet,
)
from apps.products.services.attribute_schema import (
    compute_attribute_content_hash,
    resolve_product_attribute_schema,
    validate_group_values,
)
from apps.products.services.confirm_attribute_group import supersede_stale_confirmations


@dataclass
class EditProductChangeSet:
    context: CommandContext
    change_set_public_id: UUID
    version_no: int
    group_code: str
    values: dict[str, Any]
    owner_type: str = AttributeOwnerType.PRODUCT
    owner_id: int | None = None

    def execute(self) -> AttributeGroupValue:
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

            schema = resolve_product_attribute_schema(
                change_set.organization_id,
                category_code=change_set.product.category_code,
                as_of=now,
            )
            group_definition = schema.group_by_code(self.group_code)
            normalized_values = validate_group_values(
                group_definition=group_definition,
                values=self.values,
            )
            content_hash = compute_attribute_content_hash(normalized_values)
            owner_id = self.owner_id if self.owner_id is not None else change_set.product_id

            existing_value = AttributeGroupValue.objects.filter(
                change_set=change_set,
                group_definition=group_definition,
            ).first()
            previous_hash = existing_value.content_hash if existing_value is not None else None

            group_value, _created = AttributeGroupValue.objects.update_or_create(
                change_set=change_set,
                group_definition=group_definition,
                defaults={
                    "organization_id": change_set.organization_id,
                    "owner_type": self.owner_type,
                    "owner_id": owner_id,
                    "schema_version_id": schema.schema_version.id,
                    "values_json": normalized_values,
                    "content_hash": content_hash,
                    "value_status": AttributeValueStatus.DRAFT,
                    "edited_by": actor,
                },
            )
            if previous_hash is not None and previous_hash != content_hash:
                supersede_stale_confirmations(group_value=group_value, occurred_at=now)

            change_set.version_no += 1
            change_set.save(update_fields=["version_no", "updated_at"])

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
                        "group_code": self.group_code,
                        "content_hash": content_hash,
                        "version_no": change_set.version_no,
                    },
                    request_metadata={"group_code": self.group_code},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="product_change_set.group_edited",
                    aggregate_type="product_change_set",
                    aggregate_id=change_set.public_id,
                    payload={
                        "change_set_public_id": str(change_set.public_id),
                        "group_code": self.group_code,
                        "content_hash": content_hash,
                    },
                    occurred_at=now,
                )
            )

        return group_value
