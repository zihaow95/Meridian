"""Permission-filtered audit event queries."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.audit.models import AuditEvent
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError


def list_audit_events(*, user: User, limit: int = 50) -> QuerySet[AuditEvent]:
    decision = authorize(
        subject_for(user),
        action="audit.event.read",
        resource=ResourceDescriptor(
            resource_type="audit.event",
            public_id=None,
            organization_id=user.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()

    return AuditEvent.objects.order_by("-occurred_at")[:limit]


def serialize_audit_event(event: AuditEvent) -> dict[str, object]:
    return {
        "event_id": str(event.event_id),
        "occurred_at": event.occurred_at.isoformat(),
        "action_code": event.action_code,
        "resource_type": event.resource_type,
        "resource_public_id": (str(event.resource_public_id) if event.resource_public_id else None),
        "result": event.result,
    }
