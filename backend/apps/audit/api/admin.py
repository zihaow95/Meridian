"""Audit administration read API."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.queries.events import list_audit_events


class AuditEventListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        events = list_audit_events(limit=50)
        return Response(
            [
                {
                    "event_id": str(event.event_id),
                    "occurred_at": event.occurred_at.isoformat(),
                    "action_code": event.action_code,
                    "resource_type": event.resource_type,
                    "resource_public_id": (
                        str(event.resource_public_id) if event.resource_public_id else None
                    ),
                    "result": event.result,
                    "trace_id": event.trace_id,
                }
                for event in events
            ]
        )
