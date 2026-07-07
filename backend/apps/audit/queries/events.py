"""Permission-filtered audit event queries."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.audit.models import AuditEvent


def list_audit_events(*, limit: int = 50) -> QuerySet[AuditEvent]:
    return AuditEvent.objects.order_by("-occurred_at")[:limit]
