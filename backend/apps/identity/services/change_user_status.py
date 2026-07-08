"""User status transitions without deleting identity history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationDecision,
    ResourceDescriptor,
)
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class InvalidUserStatusTransition(Exception):
    pass


class UserStatusChangeDenied(Exception):
    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


@dataclass(frozen=True)
class ChangeUserStatus:
    target: User
    status: str
    actor: User
    at: datetime | None = None
    context: CommandContext | None = None

    def execute(self) -> User:
        if self.status not in UserStatus.values:
            raise InvalidUserStatusTransition(f"Unknown status: {self.status}")

        command_context = self.context or CommandContext.for_actor(self.actor)
        now = self.at or command_context.occurred_at
        before_status = self.target.status

        with transaction.atomic():
            decision = authorize(
                subject_for(self.actor),
                action="identity.user.status_change",
                resource=ResourceDescriptor(
                    resource_type="identity.user",
                    public_id=self.target.public_id,
                    organization_id=self.target.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise UserStatusChangeDenied(decision)

            user = self.target
            user.status = self.status

            if self.status == UserStatus.ACTIVE:
                user.activated_at = now
            elif self.status == UserStatus.DISABLED:
                user.disabled_at = now
            elif self.status == UserStatus.DEPARTED:
                user.departed_at = now

            user.save(
                update_fields=[
                    "status",
                    "activated_at",
                    "disabled_at",
                    "departed_at",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="identity.user.status_change",
                    resource_type="identity.user",
                    resource_public_id=user.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    before_summary={"status": before_status},
                    after_summary={"status": user.status},
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="identity.user_status_changed",
                    aggregate_type="identity.user",
                    aggregate_id=user.public_id,
                    payload={"public_id": str(user.public_id), "status": user.status},
                    occurred_at=command_context.occurred_at,
                )
            )

        return user
