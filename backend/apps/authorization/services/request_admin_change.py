"""Request administrative changes that may require dual control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.models.admin_change import (
    AdminChangeRequest,
    SecuritySetting,
)
from apps.platform.application.command import CommandContext

DEFAULT_SETTING_KEY = "platform_security"


def get_security_setting() -> SecuritySetting:
    setting, _ = SecuritySetting.objects.get_or_create(
        setting_key=DEFAULT_SETTING_KEY,
        defaults={"dual_control_enabled": False, "version_no": 1},
    )
    return setting


@dataclass(frozen=True)
class RequestAdminChange:
    context: CommandContext
    action_type: str
    target_summary: dict[str, object]
    before_summary: dict[str, object]
    after_summary: dict[str, object]
    expires_in: timedelta = timedelta(days=7)

    def execute(self) -> AdminChangeRequest:
        with transaction.atomic():
            request = AdminChangeRequest.objects.create(
                action_type=self.action_type,
                target_summary=self.target_summary,
                proposed_by=self.context.actor,
                before_summary=self.before_summary,
                after_summary=self.after_summary,
                expires_at=self.context.occurred_at + self.expires_in,
            )
            append_event(
                AuditRecord(
                    actor=self.context.actor,
                    action_code="authorization.admin_change.request",
                    resource_type="authorization.admin_change_request",
                    resource_public_id=request.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(self.context.actor),
                    after_summary={"status": request.status, "action_type": self.action_type},
                )
            )
            return request


def dual_control_enabled() -> bool:
    return get_security_setting().dual_control_enabled
