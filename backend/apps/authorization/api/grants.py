"""Administrative grant and troubleshoot APIs."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.queries.events import list_audit_events


class AuditEventsAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        events = list_audit_events(limit=50)
        return Response(
            [
                {
                    "event_id": str(event.event_id),
                    "action_code": event.action_code,
                    "result": event.result,
                }
                for event in events
            ]
        )
