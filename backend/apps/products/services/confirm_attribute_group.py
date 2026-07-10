"""Attribute group professional confirmation commands."""

from __future__ import annotations

from dataclasses import dataclass
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
from apps.products.errors import AttributeConfirmationInvalid, ChangeSetNotEditable
from apps.products.models import (
    AttributeConfirmation,
    AttributeGroupValue,
    ChangeSetStatus,
    ConfirmationDecision,
    ProductChangeSet,
)


def supersede_stale_confirmations(*, group_value: AttributeGroupValue, occurred_at) -> int:
    return AttributeConfirmation.objects.filter(
        group_value=group_value,
        decision=ConfirmationDecision.APPROVED,
        superseded_at__isnull=True,
    ).update(superseded_at=occurred_at)


@dataclass
class ApproveAttributeGroup:
    context: CommandContext
    change_set_public_id: UUID
    group_value_public_id: UUID
    content_hash: str
    comment: str = ""

    def execute(self) -> AttributeConfirmation:
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
                action="attribute_group.confirm",
                resource=ResourceDescriptor(
                    resource_type="product_change_set",
                    public_id=change_set.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if change_set.status not in {
                ChangeSetStatus.DRAFT,
                ChangeSetStatus.IN_CONFIRMATION,
            }:
                raise ChangeSetNotEditable()

            group_value = (
                AttributeGroupValue.objects.select_related("group_definition")
                .filter(
                    public_id=self.group_value_public_id,
                    change_set=change_set,
                )
                .first()
            )
            if group_value is None:
                raise PermissionDeniedError()

            if group_value.content_hash != self.content_hash:
                raise AttributeConfirmationInvalid(
                    reason="Confirmation content hash does not match the current group value.",
                )

            supersede_stale_confirmations(group_value=group_value, occurred_at=now)

            confirmation = AttributeConfirmation.objects.create(
                organization=change_set.organization,
                change_set=change_set,
                group_value=group_value,
                content_hash=group_value.content_hash,
                confirmer=actor,
                decision=ConfirmationDecision.APPROVED,
                comment=self.comment,
                confirmed_at=now,
            )

            if change_set.status == ChangeSetStatus.DRAFT:
                change_set.status = ChangeSetStatus.IN_CONFIRMATION
                change_set.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="attribute_group.confirm",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "group_code": group_value.group_definition.group_code,
                        "content_hash": group_value.content_hash,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="attribute_group.confirmed",
                    aggregate_type="product_change_set",
                    aggregate_id=change_set.public_id,
                    payload={
                        "change_set_public_id": str(change_set.public_id),
                        "group_code": group_value.group_definition.group_code,
                    },
                    occurred_at=now,
                )
            )

        return confirmation


@dataclass
class ReturnAttributeGroup:
    context: CommandContext
    change_set_public_id: UUID
    group_value_public_id: UUID
    content_hash: str
    comment: str

    def execute(self) -> AttributeConfirmation:
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
                action="attribute_group.return",
                resource=ResourceDescriptor(
                    resource_type="product_change_set",
                    public_id=change_set.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            group_value = AttributeGroupValue.objects.filter(
                public_id=self.group_value_public_id,
                change_set=change_set,
            ).first()
            if group_value is None:
                raise PermissionDeniedError()

            if group_value.content_hash != self.content_hash:
                raise AttributeConfirmationInvalid(
                    reason="Return content hash does not match the current group value.",
                )

            supersede_stale_confirmations(group_value=group_value, occurred_at=now)

            confirmation = AttributeConfirmation.objects.create(
                organization=change_set.organization,
                change_set=change_set,
                group_value=group_value,
                content_hash=group_value.content_hash,
                confirmer=actor,
                decision=ConfirmationDecision.RETURNED,
                comment=self.comment,
                confirmed_at=now,
            )

            change_set.status = ChangeSetStatus.DRAFT
            change_set.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="attribute_group.return",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={"comment": self.comment},
                )
            )

        return confirmation


@dataclass
class ReassignAttributeConfirmer:
    context: CommandContext
    change_set_public_id: UUID
    group_value_public_id: UUID
    confirmer_user_id: int
    reason: str = ""

    def execute(self) -> AttributeGroupValue:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            change_set = ProductChangeSet.objects.filter(
                public_id=self.change_set_public_id,
                organization_id=actor.organization_id,
            ).first()
            if change_set is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="confirmer.reassign",
                resource=ResourceDescriptor(
                    resource_type="product_change_set",
                    public_id=change_set.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            group_value = AttributeGroupValue.objects.filter(
                public_id=self.group_value_public_id,
                change_set=change_set,
            ).first()
            if group_value is None:
                raise PermissionDeniedError()

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="confirmer.reassign",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "group_value_public_id": str(group_value.public_id),
                        "confirmer_user_id": self.confirmer_user_id,
                        "reason": self.reason,
                    },
                )
            )

        return group_value
