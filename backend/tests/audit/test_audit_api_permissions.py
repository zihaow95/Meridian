"""Audit API permission and response sanitization."""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event


@pytest.fixture
def audit_event(active_user):
    return append_event(
        AuditRecord(
            actor=active_user,
            action_code="identity.user.status_change",
            resource_type="identity.user",
            resource_public_id=active_user.public_id,
            result=AuditResult.SUCCESS,
            trace_id="trace-audit-api",
            occurred_at=timezone.now(),
            before_summary={"status": "ACTIVE"},
            after_summary={"status": "DISABLED"},
        )
    )


@pytest.fixture
def audit_reader_user(another_active_user, grant_action):
    grant_action(another_active_user, "audit.event.read", "audit.event")
    return another_active_user


@pytest.mark.django_db
def test_authenticated_user_without_audit_permission_cannot_list_audit_events(
    client: Client, active_user
) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/audit/events")
    assert response.status_code in {403, 404}


@pytest.mark.django_db
def test_audit_reader_can_list_sanitized_audit_events(
    client: Client, audit_reader_user, audit_event
) -> None:
    client.force_login(audit_reader_user)
    response = client.get("/api/v1/audit/events")
    assert response.status_code == 200
    row = response.json()[0]
    assert "before_summary" not in row
    assert "after_summary" not in row
