"""Product change set confirmation workflow commands."""

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
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.errors import ChangeSetNotEditable
from apps.products.models import (
    AttributeConfirmation,
    AttributeGroupValue,
    ChangeSetStatus,
    ConfirmationDecision,
    ProductChangeSet,
)
from apps.products.services.validate_publication import ValidateProductPublication


@dataclass
class SubmitProductChangeSetConfirmation:
    context: CommandContext
    change_set_public_id: UUID

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
                action="product_draft.submit",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=change_set.product.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if change_set.status != ChangeSetStatus.DRAFT:
                raise ChangeSetNotEditable()

            change_set.status = ChangeSetStatus.IN_CONFIRMATION
            change_set.save(update_fields=["status", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_draft.submit",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
        return change_set


@dataclass
class ApproveProductChangeSet:
    context: CommandContext
    change_set_public_id: UUID

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

            if change_set.created_by_id == actor.id:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="product_change_set.approve",
                resource=ResourceDescriptor(
                    resource_type="product",
                    public_id=change_set.product.public_id,
                    organization_id=change_set.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if change_set.status != ChangeSetStatus.IN_CONFIRMATION:
                raise ChangeSetNotEditable()

            pending_groups = AttributeGroupValue.objects.filter(
                change_set=change_set,
                group_definition__requires_confirmation=True,
            ).select_related("group_definition")
            for group_value in pending_groups:
                has_approval = AttributeConfirmation.objects.filter(
                    group_value=group_value,
                    content_hash=group_value.content_hash,
                    decision=ConfirmationDecision.APPROVED,
                    superseded_at__isnull=True,
                ).exists()
                if not has_approval:
                    raise ValidationFailedError(
                        details={"blocks": ["ATTRIBUTE_CONFIRMATION_REQUIRED"]},
                    )

            change_set.status = ChangeSetStatus.APPROVED
            change_set.approved_by = actor
            change_set.save(update_fields=["status", "approved_by", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="product_change_set.approve",
                    resource_type="product_change_set",
                    resource_public_id=change_set.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )

        validation = ValidateProductPublication(
            actor=actor,
            change_set_public_id=change_set.public_id,
        ).execute()
        if validation.blocks:
            # Approval does not bypass publication preflight; status remains APPROVED.
            pass
        return change_set
