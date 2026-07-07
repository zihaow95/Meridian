"""Append-only audit writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import DatabaseError

from apps.audit.models import AuditEvent
from apps.identity.models.user import User


class AuditWriteFailed(Exception):
    pass


@dataclass(frozen=True)
class AuditRecord:
    actor: User
    action_code: str
    resource_type: str
    resource_public_id: UUID | None
    result: str
    trace_id: str
    occurred_at: Any
    acting_roles_snapshot: list[str] | None = None
    before_summary: dict[str, Any] | None = None
    after_summary: dict[str, Any] | None = None
    reason: str = ""
    request_metadata: dict[str, Any] | None = None
    related_snapshot_ids: list[str] | None = None


def append_event(record: AuditRecord) -> AuditEvent:
    try:
        return AuditEvent.objects.create(
            occurred_at=record.occurred_at,
            actor_user=record.actor,
            acting_roles_snapshot=record.acting_roles_snapshot or [],
            action_code=record.action_code,
            resource_type=record.resource_type,
            resource_public_id=record.resource_public_id,
            result=record.result,
            before_summary=record.before_summary or {},
            after_summary=record.after_summary or {},
            reason=record.reason,
            trace_id=record.trace_id,
            request_metadata=record.request_metadata or {},
            related_snapshot_ids=record.related_snapshot_ids or [],
        )
    except DatabaseError as exc:
        raise AuditWriteFailed("Failed to append audit event.") from exc
