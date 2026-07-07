"""Create time-limited special authorization grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.models.special_grant import SpecialGrant, SpecialGrantStatus
from apps.authorization.policies.engine import authorize
from apps.authorization.services.assign_role import _subject_for
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext


class GrantExceedsGrantorScope(Exception):
    pass


@dataclass(frozen=True)
class CreateSpecialGrant:
    context: CommandContext
    grantee: User
    resource_type: str
    resource_public_id: UUID | None
    actions: list[str]
    max_sensitivity_level: str
    purpose: str
    valid_for: timedelta = timedelta(hours=8)

    def execute(self) -> SpecialGrant:
        for action in self.actions:
            decision = authorize(
                _subject_for(self.context.actor),
                action=action,
                resource=ResourceDescriptor(
                    resource_type=self.resource_type,
                    public_id=self.resource_public_id,
                    organization_id=self.grantee.organization_id,
                    sensitivity_level=self.max_sensitivity_level,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise GrantExceedsGrantorScope()

        if self.max_sensitivity_level not in DataSensitivityLevel.values:
            raise ValueError(f"Unknown sensitivity level: {self.max_sensitivity_level}")

        now = self.context.occurred_at
        with transaction.atomic():
            grant = SpecialGrant.objects.create(
                grantee=self.grantee,
                grantor=self.context.actor,
                resource_type=self.resource_type,
                resource_public_id=self.resource_public_id,
                actions=self.actions,
                max_sensitivity_level=self.max_sensitivity_level,
                valid_from=now,
                valid_to=now + self.valid_for,
                status=SpecialGrantStatus.ACTIVE,
                purpose=self.purpose,
            )
            append_event(
                AuditRecord(
                    actor=self.context.actor,
                    action_code="authorization.special_grant.create",
                    resource_type="authorization.special_grant",
                    resource_public_id=grant.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(self.context.actor),
                    after_summary={"actions": self.actions, "grantee": str(self.grantee.public_id)},
                    reason=self.purpose,
                )
            )
            return grant
