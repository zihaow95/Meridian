"""Audit append-only invariants."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.audit.services.append_event import AuditRecord, append_event
from apps.identity.models.user import UserStatus
from apps.identity.services.change_user_status import ChangeUserStatus


@pytest.mark.django_db
def test_append_event_creates_immutable_record(active_user) -> None:
    event = append_event(
        AuditRecord(
            actor=active_user,
            action_code="identity.user.status_change",
            resource_type="identity.user",
            resource_public_id=active_user.public_id,
            result="SUCCESS",
            trace_id="trace-1",
            occurred_at=active_user.created_at,
            after_summary={"status": UserStatus.ACTIVE},
        )
    )
    assert AuditEvent.objects.filter(pk=event.pk).exists()
    import apps.audit.services.append_event as append_module

    assert not hasattr(append_module, "update_event")
    assert not hasattr(append_module, "delete_event")


@pytest.mark.django_db
def test_status_change_writes_audit_event(active_user) -> None:
    ChangeUserStatus(
        actor=active_user,
        target=active_user,
        status=UserStatus.DISABLED,
    ).execute()
    assert AuditEvent.objects.filter(action_code="identity.user.status_change").exists()
