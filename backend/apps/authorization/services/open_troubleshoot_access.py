"""Open time-limited troubleshooting access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.models.troubleshoot import TroubleshootAccess, TroubleshootAccessStatus
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext


@dataclass(frozen=True)
class OpenTroubleshootAccess:
    context: CommandContext
    user: User
    resource_type: str
    resource_public_id: UUID | None
    actions: list[str]
    max_sensitivity_level: str
    purpose: str
    valid_for: timedelta = timedelta(hours=2)

    def execute(self) -> TroubleshootAccess:
        now = self.context.occurred_at
        with transaction.atomic():
            access = TroubleshootAccess.objects.create(
                user=self.user,
                opened_by=self.context.actor,
                resource_type=self.resource_type,
                resource_public_id=self.resource_public_id,
                actions=self.actions,
                max_sensitivity_level=self.max_sensitivity_level,
                valid_from=now,
                valid_to=now + self.valid_for,
                status=TroubleshootAccessStatus.ACTIVE,
                purpose=self.purpose,
            )
            append_event(
                AuditRecord(
                    actor=self.context.actor,
                    action_code="troubleshoot_access.open",
                    resource_type="authorization.troubleshoot_access",
                    resource_public_id=access.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(self.context.actor),
                    after_summary={"user": str(self.user.public_id), "actions": self.actions},
                    reason=self.purpose,
                )
            )
            return access
